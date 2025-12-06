"""
YABS (Yet Another Benchmark Script) workload plugin.

This plugin downloads and executes the upstream yabs.sh script to run
combined CPU/disk/network benchmarks. It avoids Geekbench by default to
reduce external dependencies/licensing friction.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Type, Any

from ...plugin_system.interface import WorkloadPlugin, WorkloadIntensity
from ...plugin_system.base_generator import BaseGenerator

logger = logging.getLogger(__name__)

YABS_URL = "https://raw.githubusercontent.com/masonr/yet-another-bench-script/master/yabs.sh"


@dataclass
class YabsConfig:
    """Configuration for the YABS workload."""

    skip_disk: bool = False
    skip_network: bool = False
    skip_geekbench: bool = True
    skip_cleanup: bool = True
    output_dir: Path = Path("/tmp")
    extra_args: List[str] = field(default_factory=list)
    debug: bool = False


class YabsGenerator(BaseGenerator):
    """Generator that runs the upstream yabs.sh script."""

    def __init__(self, config: YabsConfig):
        super().__init__("YabsGenerator")
        self.config = config
        self._process: Optional[subprocess.CompletedProcess[str]] = None

    def _validate_environment(self) -> bool:
        """Ensure required tools are present and output dir is writable."""
        for tool in ("curl", "wget", "bash"):
            if shutil.which(tool) is None:
                logger.error("Required tool missing: %s", tool)
                return False
        try:
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Failed to create output_dir %s: %s", self.config.output_dir, exc)
            return False
        if not os.access(self.config.output_dir, os.W_OK):
            logger.error("Output dir not writable: %s", self.config.output_dir)
            return False
        return True

    def _run_command(self) -> None:
        """Download and execute yabs.sh with configured flags."""
        if not self._validate_environment():
            self._result = {"error": "Environment validation failed"}
            self._is_running = False
            return

        script_path: Optional[Path] = None
        try:
            # Download script to a temp location
            fd, path_str = tempfile.mkstemp(prefix="yabs-", suffix=".sh")
            os.close(fd)
            script_path = Path(path_str)
            dl_cmd = ["curl", "-sLo", str(script_path), YABS_URL]
            self._run_checked(dl_cmd, "Failed to download yabs.sh")
            script_path.chmod(0o755)

            args: List[str] = [str(script_path)]
            if self.config.skip_disk:
                args.append("-f")  # skip fio
            if self.config.skip_network:
                args.append("-i")  # skip iperf
            if self.config.skip_geekbench:
                args.append("-g")  # skip geekbench
            if self.config.skip_cleanup:
                args.append("-c")  # skip cleanup
            if self.config.extra_args:
                args.extend(self.config.extra_args)

            env = os.environ.copy()
            # Prevent interactive prompts
            env.setdefault("YABS_NONINTERACTIVE", "1")

            if self.config.debug:
                logger.info("Running YABS command: %s", " ".join(args))

            run = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self._process = run

            log_path = self.config.output_dir / "yabs.log"
            try:
                log_path.write_text((run.stdout or "") + "\n" + (run.stderr or ""))
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug("Failed to write yabs log: %s", exc)

            self._result = {
                "stdout": run.stdout or "",
                "stderr": run.stderr or "",
                "returncode": run.returncode,
                "command": " ".join(args),
                "log_path": str(log_path),
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("YABS execution error: %s", exc)
            self._result = {"error": str(exc)}
        finally:
            if script_path and script_path.exists():
                try:
                    script_path.unlink()
                except Exception:
                    pass
            self._is_running = False

    def _run_checked(self, cmd: List[str], error_message: str) -> None:
        """Run a command and raise on failure."""
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(
                f"{error_message}: rc={completed.returncode}, stderr={completed.stderr}"
            )

    def _stop_workload(self) -> None:
        """YABS runs to completion; nothing to stop mid-flight."""
        return


class YabsPlugin(WorkloadPlugin):
    """Plugin wrapper for YABS."""

    @property
    def name(self) -> str:
        return "yabs"

    @property
    def description(self) -> str:
        return "Yet Another Bench Script (CPU/disk/network)"

    @property
    def config_cls(self) -> Type[YabsConfig]:
        return YabsConfig

    def create_generator(self, config: YabsConfig | dict) -> YabsGenerator:
        if isinstance(config, dict):
            config = YabsConfig(**config)
        return YabsGenerator(config)

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[YabsConfig]:
        # Intensities map to which portions we run; Geekbench remains skipped by default.
        # Durations: each curl/wget+iperf+fio run adds seconds; cleanup skipped on lower levels to save time.
        if level == WorkloadIntensity.LOW:
            # Quick check: network only, skip disk to keep runtime short.
            return YabsConfig(
                skip_disk=True,
                skip_network=False,
                skip_geekbench=True,
                skip_cleanup=True,
            )
        if level == WorkloadIntensity.MEDIUM:
            # Network + disk, skip cleanup for speed.
            return YabsConfig(
                skip_disk=False,
                skip_network=False,
                skip_geekbench=True,
                skip_cleanup=True,
            )
        if level == WorkloadIntensity.HIGH:
            # Full run, include cleanup to leave system tidy.
            return YabsConfig(
                skip_disk=False,
                skip_network=False,
                skip_geekbench=True,
                skip_cleanup=False,
            )
        return None

    def get_required_apt_packages(self) -> List[str]:
        # YABS uses curl/wget, fio, iperf3, tar, bc.
        return ["curl", "wget", "fio", "iperf3", "bc", "tar"]

    def get_required_local_tools(self) -> List[str]:
        return ["bash", "curl", "wget"]

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

    def get_ansible_setup_path(self) -> Optional[Path]:
        return Path(__file__).parent / "ansible" / "setup.yml"

    def get_ansible_teardown_path(self) -> Optional[Path]:
        return None


PLUGIN = YabsPlugin()
