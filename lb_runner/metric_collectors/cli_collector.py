"""
CLI metric collector implementation.

This module collects system metrics by invoking external CLI tools and parsing their output.
"""

import logging
import subprocess
import shlex
import jc
from typing import Dict, Any, List

from ._base_collector import BaseCollector
from .aggregators import aggregate_cli


logger = logging.getLogger(__name__)


class CLICollector(BaseCollector):
    """Metric collector using CLI commands."""
    
    def __init__(self, name: str = "CLICollector", interval_seconds: float = 5.0, commands: List[str] = None):
        """
        Initialize the CLI collector.

        Args:
            name: Name of the collector
            interval_seconds: Sampling interval in seconds
            commands: List of CLI commands to run
        """
        super().__init__(name, interval_seconds)
        self.commands = commands if commands else []
        self._failed_commands: set[str] = set()

    def _collect_metrics(self) -> Dict[str, Any]:
        """
        Collect metrics by running CLI commands.
        
        Returns:
            Dictionary containing metric names and their values
        """
        metrics = {}
        for command in self.commands:
            if command in self._failed_commands:
                continue
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

                tool_name = shlex.split(command)[0]
                parsed = None

                # Special-case sar: jc may not ship a parser; fall back to manual parsing
                if tool_name == "sar":
                    parsed = self._parse_sar(output)
                else:
                    try:
                        parsed = jc.parse(tool_name, output)
                    except Exception as e:  # jc may not ship a parser; treat as non-fatal
                        logger.warning("Failed to parse output for '%s' (%s); disabling this command", tool_name, e)
                        self._failed_commands.add(command)
                        continue

                if isinstance(parsed, list):
                    parsed = parsed[0] if parsed and isinstance(parsed[0], dict) else {}
                if isinstance(parsed, dict):
                    metrics.update(parsed)

            except subprocess.TimeoutExpired:
                logger.error(f"Command '{command}' timed out after {self.interval_seconds}s")
                self._failed_commands.add(command)
            except subprocess.CalledProcessError as e:
                logger.error(f"Command '{command}' failed to execute: {e}")
                self._failed_commands.add(command)
            except Exception as e:
                logger.error(f"Error parsing output for command '{command}': {e}")
                self._failed_commands.add(command)

        return metrics

    def _parse_sar(self, output: str) -> Dict[str, Any]:
        """
        Minimal parser for `sar -u` output when jc lacks a parser.

        Returns an empty dict when parsing fails.
        """
        lines = [ln for ln in output.splitlines() if ln.strip()]
        if not lines:
            return {}

        # Find the last data line (skip header)
        data_line = None
        for ln in reversed(lines):
            # Skip lines starting with "Average:" or blank; prefer numeric timestamp rows
            parts = ln.split()
            if len(parts) < 3:
                continue
            # crude check: first token contains ':' (time)
            if ":" in parts[0]:
                data_line = parts
                break
            if parts[0].lower() == "average:":
                data_line = parts[1:]
                break

        if not data_line or len(data_line) < 5:
            return {}

        # sar -u typically: time user nice system iowait steal idle
        try:
            # align columns from the end to be safer
            user, nice, system, iowait, steal, idle = map(float, data_line[-6:])
        except Exception:
            return {}

        return {
            "sar_user_pct": user,
            "sar_nice_pct": nice,
            "sar_system_pct": system,
            "sar_iowait_pct": iowait,
            "sar_steal_pct": steal,
            "sar_idle_pct": idle,
        }

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

