"""
DD workload generator implementation.
Modular plugin version.
"""

import logging
import os
import platform
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, List, Optional

from pydantic import Field

from ...interface import SimpleWorkloadPlugin, WorkloadIntensity, BasePluginConfig
from ...base_generator import CommandGenerator, CommandSpec

logger = logging.getLogger(__name__)


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
    bs: str = Field(default="1M", description="Block size for reads/writes (e.g., 1M, 4k)")
    count: Optional[int] = Field(default=None, ge=1, description="Number of blocks to copy (None means run until stopped by runner duration)")
    conv: Optional[str] = Field(default="fdatasync", description="Conversion options (e.g., fdatasync, noerror, sync)")
    oflag: Optional[str] = Field(default="direct", description="Output flags (e.g., direct, sync, dsync)")
    timeout: int = Field(default=60, gt=0, description="Timeout in seconds for dd execution")
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

        conv = config.conv
        oflag = config.oflag

        if is_macos:
            if oflag == "direct":
                logger.debug("Ignoring 'oflag=direct' on macOS (not supported by BSD dd)")
                oflag = None
            if conv == "fdatasync":
                logger.debug("Mapping 'conv=fdatasync' to 'conv=sync' on macOS")
                conv = "sync"

        if conv:
            cmd.append(f"conv={conv}")
        if oflag:
            cmd.append(f"oflag={oflag}")

        cmd.append("status=progress")
        return CommandSpec(cmd=cmd)


class DDGenerator(CommandGenerator):
    """Workload generator using dd command."""

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

    def _consume_process_output(
        self, proc: subprocess.Popen[str]
    ) -> tuple[str, str]:
        stdout, stderr = proc.communicate(timeout=self._timeout_seconds())
        return stdout or "", stderr or ""

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
        try:
            result = subprocess.run(["which", "dd"], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("dd command not found")
                return False
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error checking for dd: %s", exc)
            return False

        if not self.config.of_path:
            logger.error("Output path is empty")
            return False

        output_dir = Path(self.config.of_path).expanduser().parent
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Failed to create output directory %s: %s", output_dir, exc)
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
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup.yml"

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[DDConfig]:
        if level == WorkloadIntensity.LOW:
            return DDConfig(
                bs="1M",
                count=1024, # 1GB
            )
        elif level == WorkloadIntensity.MEDIUM:
            return DDConfig(
                bs="4M",
                count=2048, # 8GB
            )
        elif level == WorkloadIntensity.HIGH:
            return DDConfig(
                bs="4M",
                count=8192, # 32GB
                oflag="direct",
                conv="fdatasync"
            )
        return None


PLUGIN = DDPlugin()
