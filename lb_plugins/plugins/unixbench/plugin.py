"""
UnixBench workload plugin for linux-benchmark-lib.

Builds and runs UnixBench from source (Ubuntu package is outdated/broken).
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, List, Optional, Type

from pydantic import Field

from ...base_generator import CommandGenerator
from ...interface import BasePluginConfig, WorkloadIntensity, WorkloadPlugin


logger = logging.getLogger(__name__)


class UnixBenchConfig(BasePluginConfig):
    """Configuration for UnixBench workload."""

    threads: int = Field(default=1, gt=0, description="Passed as -c to Run.")
    iterations: int = Field(default=1, gt=0, description="Passed as -i to Run.")
    tests: list[str] = Field(default_factory=list, description="If empty, run default suite.")
    workdir: Path = Field(default=Path("/opt/UnixBench"), description="Where Run lives.")
    extra_args: list[str] = Field(default_factory=list)
    debug: bool = Field(default=False)


class UnixBenchGenerator(CommandGenerator):
    """Run UnixBench as a workload generator."""

    def __init__(self, config: UnixBenchConfig, name: str = "UnixBenchGenerator"):
        super().__init__(name, config)

    def _build_command(self) -> List[str]:
        cmd: List[str] = ["./Run"]
        cmd.extend(["-c", str(self.config.threads)])
        cmd.extend(["-i", str(self.config.iterations)])
        if self.config.tests:
            cmd.extend(self.config.tests)
        if self.config.debug:
            cmd.append("--verbose")
        cmd.extend(self.config.extra_args)
        return cmd

    def _popen_kwargs(self) -> dict[str, Any]:
        return {
            "cwd": self.config.workdir,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
        }

    def _timeout_seconds(self) -> Optional[int]:
        return self.config.timeout_buffer + max(120, 60 * self.config.iterations)

    def _log_command(self, cmd: list[str]) -> None:
        logger.info("Running UnixBench in %s: %s", self.config.workdir, " ".join(cmd))

    def _validate_environment(self) -> bool:
        # Check Run exists in workdir
        run_path = self.config.workdir / "Run"
        if not run_path.exists():
            logger.error("UnixBench Run script not found at %s", run_path)
            return False
        if not os.access(run_path, os.X_OK):
            logger.error("UnixBench Run script at %s is not executable", run_path)
            return False
        return True

    def _log_failure(
        self, returncode: int, stdout: str, stderr: str, cmd: list[str]
    ) -> None:
        output = stdout or stderr
        if output:
            logger.error("UnixBench failed with return code %s: %s", returncode, output)
        else:
            logger.error("UnixBench failed with return code %s", returncode)


class UnixBenchPlugin(WorkloadPlugin):
    """Plugin definition for UnixBench."""

    @property
    def name(self) -> str:
        return "unixbench"

    @property
    def description(self) -> str:
        return "UnixBench micro-benchmark suite built from source"

    @property
    def config_cls(self) -> Type[UnixBenchConfig]:
        return UnixBenchConfig

    def create_generator(self, config: UnixBenchConfig | dict) -> UnixBenchGenerator:
        if isinstance(config, dict):
            config = UnixBenchConfig(**config)
        return UnixBenchGenerator(config)

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[UnixBenchConfig]:
        cpu_count = os.cpu_count() or 2
        if level == WorkloadIntensity.LOW:
            return UnixBenchConfig(threads=1, iterations=1)
        if level == WorkloadIntensity.MEDIUM:
            return UnixBenchConfig(threads=max(2, cpu_count // 2), iterations=1)
        if level == WorkloadIntensity.HIGH:
            return UnixBenchConfig(threads=max(2, cpu_count), iterations=2)
        return None

    def get_required_apt_packages(self) -> List[str]:
        # Build deps; UnixBench itself is built from source
        return ["build-essential", "libx11-dev", "libgl1-mesa-dev", "libxext-dev", "wget"]

    def get_required_local_tools(self) -> List[str]:
        return ["make", "gcc", "wget"]

    def get_dockerfile_path(self) -> Optional[Path]:
        path = Path(__file__).parent / "Dockerfile"
        return path if path.exists() else None

    def get_ansible_setup_path(self) -> Optional[Path]:
        return Path(__file__).parent / "ansible" / "setup.yml"


PLUGIN = UnixBenchPlugin()
