"""
CLI metric collector implementation.

This module collects system metrics by invoking external CLI tools and parsing their output.
"""

import subprocess
import logging
from typing import Dict, Any
from ._base_collector import BaseCollector
import jc


logger = logging.getLogger(__name__)


class CLICollector(BaseCollector):
    """Metric collector using CLI commands."""
    
    def __init__(self, name: str = "CLICollector", interval_seconds: float = 1.0, commands: list = None):
        """
        Initialize the CLI collector.

        Args:
            name: Name of the collector
            interval_seconds: Sampling interval in seconds
            commands: List of CLI commands to run
        """
        super().__init__(name, interval_seconds)
        self.commands = commands if commands else []

    def _collect_metrics(self) -> Dict[str, Any]:
        """
        Collect metrics by running CLI commands.
        
        Returns:
            Dictionary containing metric names and their values
        """
        metrics = {}
        for command in self.commands:
            try:
                # Run the command and decode the output
                result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, check=True)
                output = result.stdout.decode().strip()

                # Parse the output using jc (assuming JSON-like parsing available)
                parsed = jc.parse(command.split()[0], output)

                # Merge parsed results into metrics
                metrics.update(parsed)

            except subprocess.CalledProcessError as e:
                logger.error(f"Command '{command}' failed to execute: {e}")
            except Exception as e:
                logger.error(f"Error parsing output for command '{command}': {e}")

        return metrics

    def _validate_environment(self) -> bool:
        """
        Validate that the CLI tools are available in the environment.

        Returns:
            True if all commands are available, False otherwise
        """
        for command in self.commands:
            tool = command.split()[0]
            if not self._is_tool_available(tool):
                logger.error(f"Required tool '{tool}' is not available")
                return False

        return True

    def _is_tool_available(self, tool: str) -> bool:
        """
        Check if the given tool is available in the PATH.

        Args:
            tool: Name of the tool

        Returns:
            True if available, False otherwise
        """
        result = subprocess.run(["which", tool], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.returncode == 0

