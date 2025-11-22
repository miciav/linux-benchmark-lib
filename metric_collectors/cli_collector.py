"""
CLI metric collector implementation.

This module collects system metrics by invoking external CLI tools and parsing their output.
"""

import subprocess
import logging
import shlex
from typing import Dict, Any, List
from ._base_collector import BaseCollector
import jc


logger = logging.getLogger(__name__)


class CLICollector(BaseCollector):
    """Metric collector using CLI commands."""
    
    def __init__(self, name: str = "CLICollector", interval_seconds: float = 1.0, commands: List[str] = None):
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
                # Run the command safely with a timeout to avoid hanging collectors
                # Use shell=True to support pipes/redirections in custom commands
                result = subprocess.run(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True,
                    timeout=self.interval_seconds + 1.0,
                )
                output = result.stdout.strip()

                # Parse the output using jc; handle list/dict results
                # We need the first token of the command for jc to know which parser to use
                tool_name = shlex.split(command)[0]
                parsed = jc.parse(tool_name, output)
                if isinstance(parsed, list):
                    parsed = parsed[0] if parsed and isinstance(parsed[0], dict) else {}
                if isinstance(parsed, dict):
                    metrics.update(parsed)

            except subprocess.TimeoutExpired:
                logger.error(f"Command '{command}' timed out after {self.interval_seconds}s")
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
