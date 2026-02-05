"""DD workload generator implementation."""

import logging
import os
import platform
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd
from pydantic import Field

from ...interface import BasePluginConfig, SimpleWorkloadPlugin, WorkloadIntensity
from ...base_generator import CommandSpec
from ..command_base import ProcessCommandGenerator

logger = logging.getLogger(__name__)

_DD_SUMMARY_RE = re.compile(
    r"(?P<bytes>\d+) bytes .* copied, "
    r"(?P<seconds>[0-9.]+) s, "
    r"(?P<rate>[0-9.]+) (?P<rate_unit>\S+/s)"
)


def _summarize_dd_stderr(stderr: str) -> dict[str, Any]:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return {}
    for line in reversed(lines):
        match = _DD_SUMMARY_RE.search(line)
        if match:
            bytes_val = int(match.group("bytes"))
            seconds = float(match.group("seconds"))
            return {
                "dd_summary": line,
                "dd_bytes": bytes_val,
                "dd_seconds": seconds,
                "dd_rate": float(match.group("rate")),
                "dd_rate_unit": match.group("rate_unit"),
                "dd_bytes_per_sec": (bytes_val / seconds) if seconds else None,
            }
    return {"dd_summary": lines[-1]}


def _default_dd_output_path() -> str:
    temp_root = Path(tempfile.gettempdir())
    unique = uuid.uuid4().hex
    return str(temp_root / f"lb_dd_test_{os.getpid()}_{unique}")


class DDConfig(BasePluginConfig):
    """Configuration for dd workload."""

    if_path: str = Field(default="/dev/zero", description="Input file path")
    of_path: str = Field(
        default_factory=_default_dd_output_path,
        description="Output file path",
    )
    bs: str = Field(
        default="1M",
        description="Block size for reads/writes (e.g., 1M, 4k)",
    )
    count: Optional[int] = Field(
        default=None,
        ge=1,
        description="Number of blocks to copy (None means run until stopped)",
    )
    conv: Optional[str] = Field(
        default="fdatasync",
        description="Conversion options (e.g., fdatasync, noerror, sync)",
    )
    oflag: Optional[str] = Field(
        default="direct",
        description="Output flags (e.g., direct, sync, dsync)",
    )
    timeout: int = Field(
        default=60,
        gt=0,
        description="Timeout in seconds for dd execution",
    )
    debug: bool = Field(default=False, description="Enable debug logging")


class _DDCommandBuilder:
    def build(self, config: DDConfig) -> CommandSpec:
        cmd = ["dd"]
        is_macos = platform.system() == "Darwin"

        cmd.append(f"if={config.if_path}")
        cmd.append(f"of={config.of_path}")
        cmd.append(f"bs={config.bs}")

        if config.count is not None:
            cmd.append(f"count={config.count}")

        conv, oflag = _normalize_dd_options(config, is_macos)

        if conv:
            cmd.append(f"conv={conv}")
        if oflag:
            cmd.append(f"oflag={oflag}")

        cmd.append("status=progress")
        return CommandSpec(cmd=cmd)


class DDGenerator(ProcessCommandGenerator):
    """Workload generator using dd command."""

    tool_name = "dd"

    def __init__(self, config: DDConfig, name: str = "DDGenerator"):
        """
        Initialize the dd generator.

        Args:
            config: Configuration for dd
            name: Name of the generator
        """
        self._command_builder = _DDCommandBuilder()
        super().__init__(name, config, command_builder=self._command_builder)

    def _build_command(self) -> List[str]:
        return self._command_builder.build(self.config).cmd

    def _popen_kwargs(self) -> dict[str, Any]:
        return {"stdout": subprocess.DEVNULL, "stderr": subprocess.PIPE, "text": True}

    def _log_command(self, cmd: list[str]) -> None:
        if self.config.debug:
            logger.info("Running command (DEBUG): %s", " ".join(cmd))
        else:
            logger.info("Running command: %s", " ".join(cmd))

    def _log_failure(
        self, returncode: int, stdout: str, stderr: str, cmd: list[str]
    ) -> None:
        logger.error("dd failed with return code %s", returncode)
        if stderr:
            logger.error("stderr: %s", stderr)

    def _after_run(
        self,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> None:
        if self.config.debug and stderr:
            logger.info("dd stderr output:\n%s", stderr)

        output_path = Path(self.config.of_path).resolve()
        tmp_dir = Path(tempfile.gettempdir()).resolve()
        if output_path.exists() and output_path.is_relative_to(tmp_dir):
            try:
                output_path.unlink()
                logger.info("Cleaned up test file: %s", output_path)
            except OSError as exc:
                logger.warning("Failed to clean up test file: %s", exc)

    def _validate_environment(self) -> bool:
        """
        Validate that dd is available and output path is writable.

        Returns:
            True if dd is available and path is writable, False otherwise
        """
        if not super()._validate_environment():
            return False

        if not self.config.of_path:
            logger.error("Output path is empty")
            return False

        output_dir = Path(self.config.of_path).expanduser().parent
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error(
                "Failed to create output directory %s: %s", output_dir, exc
            )
            return False

        if not output_dir.is_dir():
            logger.error("Output directory %s is not a directory", output_dir)
            return False

        if not os.access(output_dir, os.W_OK):
            logger.error("Output directory %s is not writable", output_dir)
            return False

        return True


class DDPlugin(SimpleWorkloadPlugin):
    """Plugin definition for dd."""

    NAME = "dd"
    DESCRIPTION = "Sequential disk I/O via dd"
    CONFIG_CLS = DDConfig
    GENERATOR_CLS = DDGenerator
    REQUIRED_APT_PACKAGES = ["coreutils"]
    REQUIRED_LOCAL_TOOLS = ["dd"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[DDConfig]:
        if level == WorkloadIntensity.LOW:
            return DDConfig(
                bs="1M",
                count=1024,
            )
        if level == WorkloadIntensity.MEDIUM:
            return DDConfig(
                bs="4M",
                count=2048,
            )
        if level == WorkloadIntensity.HIGH:
            return DDConfig(
                bs="4M",
                count=8192,
                oflag="direct",
                conv="fdatasync",
            )
        return None

    def export_results_to_csv(
        self,
        results: List[dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> List[Path]:
        rows = [
            row
            for entry in results
            if (row := _build_dd_row(entry, run_id, test_name)) is not None
        ]

        if not rows:
            return []

        df = pd.DataFrame(rows)
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{test_name}_plugin.csv"
        df.to_csv(csv_path, index=False)
        return [csv_path]


PLUGIN = DDPlugin()


def _normalize_dd_options(
    config: DDConfig, is_macos: bool
) -> tuple[str | None, str | None]:
    conv = config.conv
    oflag = config.oflag
    if not is_macos:
        return conv, oflag
    if oflag == "direct":
        logger.debug(
            "Ignoring 'oflag=direct' on macOS (not supported by BSD dd)"
        )
        oflag = None
    if conv == "fdatasync":
        logger.debug("Mapping 'conv=fdatasync' to 'conv=sync' on macOS")
        conv = "sync"
    return conv, oflag


def _build_dd_row(
    entry: dict[str, Any],
    run_id: str,
    test_name: str,
) -> dict[str, Any] | None:
    row = {
        "run_id": run_id,
        "workload": test_name,
        "repetition": entry.get("repetition"),
        "duration_seconds": entry.get("duration_seconds"),
        "success": entry.get("success"),
    }
    gen_result = entry.get("generator_result") or {}
    if not isinstance(gen_result, dict):
        return row
    stderr = gen_result.get("stderr") or ""
    row["generator_stdout"] = gen_result.get("stdout") or ""
    row["generator_returncode"] = gen_result.get("returncode")
    row["generator_command"] = gen_result.get("command")
    row["generator_max_retries"] = gen_result.get("max_retries")
    row["generator_tags"] = gen_result.get("tags")
    if entry.get("success"):
        summary = _summarize_dd_stderr(stderr)
        row.update(summary)
        row["generator_stderr"] = summary.get("dd_summary", "")
    else:
        row["generator_stderr"] = stderr
    return row
