"""CLI metric collector implementation.

This module collects system metrics by invoking external CLI tools and parsing
their output.
"""

import logging
import shlex
import subprocess
from pathlib import Path
from typing import Any

import jc

from ._base_collector import BaseCollector

logger = logging.getLogger(__name__)


def _merge_parsed(tool_name: str, parsed: Any) -> dict[str, Any]:
    """Flatten one command's jc output into metrics without losing rows.

    jc returns one dict per device or per CPU, so a multi-row result cannot be
    flattened into a single dict without collision. The first row is merged flat
    so the existing aggregator schema keeps working, and every row is preserved
    under ``<tool>_rows`` so nothing is silently discarded.

    Args:
        tool_name: Name of the tool, used to namespace the per-row detail
        parsed: Whatever jc returned

    Returns:
        A flat dict of metrics

    """
    if isinstance(parsed, list):
        rows = [row for row in parsed if isinstance(row, dict)]
        if not rows:
            return {}
        if len(rows) > 1:
            logger.warning(
                "Command '%s' produced %d rows; keeping the first flat and all "
                "of them under '%s_rows'",
                tool_name,
                len(rows),
                tool_name,
            )
            return {**rows[0], f"{tool_name}_rows": rows}
        return dict(rows[0])
    if isinstance(parsed, dict):
        return dict(parsed)
    return {}


class CLICollector(BaseCollector):
    """Metric collector using CLI commands."""

    def __init__(
        self,
        name: str = "CLICollector",
        interval_seconds: float = 5.0,
        commands: list[str] | None = None,
    ) -> None:
        """Initialize the CLI collector.

        Args:
            name: Name of the collector
            interval_seconds: Sampling interval in seconds
            commands: List of CLI commands to run

        """
        super().__init__(name, interval_seconds)
        self.commands: list[str] = list(commands or [])
        self._failed_commands: set[str] = set()

    def _collect_metrics(self) -> dict[str, Any]:
        """Collect metrics by running CLI commands.

        Returns:
            Dictionary containing metric names and their values

        """
        metrics = {}
        for command in self.commands:
            if command in self._failed_commands:
                continue
            try:
                # Run the command safely with a timeout to avoid hanging collectors
                # shell=True is required to support the pipes and redirections
                # that these collector commands use (e.g. "vmstat 1 | tail -5").
                # The command string comes from the user's own benchmark config,
                # not from a remote or untrusted source, and it runs with the
                # privileges the operator already has.
                result = subprocess.run(
                    command,
                    shell=True,  # nosec B602
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=self.interval_seconds + 1.0,
                )
                output = result.stdout.strip()

                # jc resolves parsers by bare tool name, so a quoted path like
                # "/usr/bin/sar" must be reduced to "sar" here; otherwise jc
                # raises and the command is disabled for the rest of the run.
                # _validate_environment deliberately keeps the full token: it
                # checks the actual binary with `which`, which accepts a path.
                tool_name = Path(shlex.split(command)[0]).name
                parsed: Any = None

                # Special-case sar: jc may not ship a parser; fall back to manual
                # parsing.
                if tool_name == "sar":
                    parsed = self._parse_sar(output)
                else:
                    try:
                        parsed = jc.parse(tool_name, output)
                    except (
                        Exception
                    ) as e:  # jc may not ship a parser; treat as non-fatal
                        logger.warning(
                            "Failed to parse output for '%s' (%s); "
                            "disabling this command",
                            tool_name,
                            e,
                        )
                        self._failed_commands.add(command)
                        continue

                metrics.update(_merge_parsed(tool_name, parsed))

            except subprocess.TimeoutExpired:
                logger.error(
                    "Command '%s' timed out after %ss",
                    command,
                    self.interval_seconds,
                )
                self._failed_commands.add(command)
            except subprocess.CalledProcessError as e:
                logger.error("Command '%s' failed to execute: %s", command, e)
                self._failed_commands.add(command)
            except Exception as e:
                logger.error("Error parsing output for command '%s': %s", command, e)
                self._failed_commands.add(command)

        return metrics

    def _parse_sar(self, output: str) -> dict[str, Any]:
        """Minimal parser for `sar -u` output when jc lacks a parser.

        Returns an empty dict when parsing fails.
        """
        lines = [ln for ln in output.splitlines() if ln.strip()]
        if not lines:
            return {}

        # Find the last data line (skip header)
        data_line = None
        for ln in reversed(lines):
            # Skip lines starting with "Average:" or blank; prefer numeric
            # timestamp rows.
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
        """Drop commands whose tool is missing, keeping the ones that work.

        A missing *optional* tool must not abort the benchmark: the metrics it
        would have produced are worth less than the workload run itself. The
        collector is only unusable when nothing at all is left to run.

        Returns:
            True if at least one command can run, False otherwise

        """
        usable = []
        for command in self.commands:
            # A malformed entry must be dropped with a warning, never abort the
            # run: shlex raises on an unbalanced quote and returns [] for an
            # empty command, and both are the same class of bad config.
            try:
                parts = shlex.split(command)
            except ValueError:
                parts = []
            if not parts:
                logger.warning(
                    "Skipping CLI metric command %r: it is not parseable as a "
                    "command line",
                    command,
                )
                continue
            tool = parts[0]
            if self._is_tool_available(tool):
                usable.append(command)
            else:
                logger.warning(
                    "Skipping CLI metric command '%s': tool '%s' is not available",
                    command,
                    tool,
                )

        if not usable:
            logger.error("No CLI metric command can run in this environment")
            return False

        self.commands = usable
        return True

    def _is_tool_available(self, tool: str) -> bool:
        """Check if the given tool is available in the PATH.

        Args:
            tool: Name of the tool

        Returns:
            True if available, False otherwise

        """
        result = subprocess.run(["which", tool], capture_output=True)
        return result.returncode == 0
