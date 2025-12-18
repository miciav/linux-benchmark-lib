"""
DD workload generator implementation.
Modular plugin version.
"""

import logging
import os
import platform
import subprocess
# Removed from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Type, Any

from pydantic import Field # Added pydantic Field

from ...plugin_system.interface import WorkloadPlugin, WorkloadIntensity, BasePluginConfig # Imported BasePluginConfig
from ...plugin_system.base_generator import BaseGenerator

logger = logging.getLogger(__name__)


class DDConfig(BasePluginConfig): # Now inherits from BasePluginConfig
    """Configuration for dd workload."""

    if_path: str = Field(default="/dev/zero", description="Input file path")
    of_path: str = Field(default="/tmp/lb_dd_test", description="Output file path")
    bs: str = Field(default="1M", description="Block size for reads/writes (e.g., 1M, 4k)")
    count: Optional[int] = Field(default=None, ge=1, description="Number of blocks to copy (None means run until stopped by runner duration)")
    conv: Optional[str] = Field(default="fdatasync", description="Conversion options (e.g., fdatasync, noerror, sync)")
    oflag: Optional[str] = Field(default="direct", description="Output flags (e.g., direct, sync, dsync)")
    timeout: int = Field(default=60, gt=0, description="Timeout in seconds for dd execution")
    debug: bool = Field(default=False, description="Enable debug logging")


class DDGenerator(BaseGenerator):
    """Workload generator using dd command."""

    def __init__(self, config: DDConfig, name: str = "DDGenerator"):
        """
        Initialize the dd generator.

        Args:
            config: Configuration for dd
            name: Name of the generator
        """
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen] = None

    def _build_command(self) -> List[str]:
        """
        Build the dd command from configuration.

        Returns:
            List of command arguments
        """
        cmd = ["dd"]
        is_macos = platform.system() == "Darwin"

        cmd.append(f"if={self.config.if_path}")
        cmd.append(f"of={self.config.of_path}")
        cmd.append(f"bs={self.config.bs}")

        if self.config.count is not None:
            cmd.append(f"count={self.config.count}")

        # Platform-specific adjustments
        conv = self.config.conv
        oflag = self.config.oflag

        if is_macos:
            # BSD dd on macOS usually does not support 'oflag=direct' or 'conv=fdatasync'
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

        # status=progress is supported on recent macOS versions
        cmd.append("status=progress")

        return cmd

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

    def _run_command(self) -> None:
        """Run dd with configured parameters."""
        cmd = self._build_command()
        if self.config.debug:
            logger.info("Running command (DEBUG): %s", " ".join(cmd))
        else:
            logger.info("Running command: %s", " ".join(cmd))

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )

            stdout, stderr = self._process.communicate(timeout=self.config.timeout + self.config.timeout_buffer) # Add safety timeout

            self._result = {
                "stdout": stdout or "",
                "stderr": stderr or "",
                "returncode": self._process.returncode,
                "command": " ".join(cmd),
                "max_retries": self.config.max_retries, # Add inherited field
                "tags": self.config.tags # Add inherited field
            }

            if self.config.debug and stderr:
                logger.info("dd stderr output:\n%s", stderr)

            if self._process.returncode != 0:
                logger.error("dd failed with return code %s", self._process.returncode)
                logger.error("stderr: %s", stderr)

            output_path = Path(self.config.of_path).resolve()
            tmp_dir = Path("/tmp").resolve()
            if output_path.exists() and output_path.is_relative_to(tmp_dir):
                try:
                    output_path.unlink()
                    logger.info("Cleaned up test file: %s", output_path)
                except OSError as exc:
                    logger.warning("Failed to clean up test file: %s", exc)

        except subprocess.TimeoutExpired:
            logger.error(f"dd timed out after {self.config.timeout + self.config.timeout_buffer} seconds. Terminating process.")
            self._process.kill()
            self._process.wait()
            self._result = {"error": f"Timeout after {self.config.timeout + self.config.timeout_buffer}s", "returncode": -1}
        except Exception as exc:
            logger.error("Error running dd: %s", exc)
            self._result = {"error": str(exc), "returncode": -2}
        finally:
            self._process = None
            self._is_running = False

    def _stop_workload(self) -> None:
        """Stop dd process."""
        proc = self._process
        if proc and proc.poll() is None:
            logger.info("Terminating dd process")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing dd process")
                proc.kill()
                proc.wait()


class DDPlugin(WorkloadPlugin):
    """Plugin definition for dd."""

    @property
    def name(self) -> str:
        return "dd"

    @property
    def description(self) -> str:
        return "Sequential disk I/O via dd"

    @property
    def config_cls(self) -> Type[DDConfig]:
        return DDConfig

    def create_generator(self, config: DDConfig) -> DDGenerator: # Type hint updated
        return DDGenerator(config)

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[DDConfig]:
        if level == WorkloadIntensity.LOW:
            return DDConfig(
                bs="1M",
                count=1024, # 1GB
                oflag="direct"
            )
        elif level == WorkloadIntensity.MEDIUM:
            return DDConfig(
                bs="4M",
                count=2048, # 8GB
                oflag="direct"
            )
        elif level == WorkloadIntensity.HIGH:
            return DDConfig(
                bs="4M",
                count=8192, # 32GB
                oflag="direct",
                conv="fdatasync"
            )
        return None

    def get_required_apt_packages(self) -> List[str]:
        return ["coreutils"]

    def get_required_local_tools(self) -> List[str]:
        return ["dd"]

    def get_ansible_setup_path(self) -> Optional[Path]:
        return Path(__file__).parent / "ansible" / "setup.yml"

    def get_ansible_teardown_path(self) -> Optional[Path]:
        return None


PLUGIN = DDPlugin()
