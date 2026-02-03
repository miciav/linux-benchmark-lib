"""
UnixBench workload plugin for linux-benchmark-lib.

Builds and runs UnixBench from source (Ubuntu package is outdated/broken).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from pydantic import Field

from ...base_generator import CommandSpec
from ...interface import BasePluginConfig, WorkloadIntensity, SimpleWorkloadPlugin
from ..command_base import StdoutCommandGenerator


logger = logging.getLogger(__name__)


class UnixBenchConfig(BasePluginConfig):
    """Configuration for UnixBench workload."""

    threads: int = Field(default=1, gt=0, description="Passed as -c to Run.")
    iterations: int = Field(default=1, gt=0, description="Passed as -i to Run.")
    tests: list[str] = Field(default_factory=list, description="If empty, run default suite.")
    workdir: Path = Field(default=Path("/opt/UnixBench"), description="Where Run lives.")
    extra_args: list[str] = Field(default_factory=list)
    debug: bool = Field(default=False)


class _UnixBenchCommandBuilder:
    def build(self, config: UnixBenchConfig) -> CommandSpec:
        cmd: List[str] = ["./Run"]
        cmd.extend(["-c", str(config.threads)])
        cmd.extend(["-i", str(config.iterations)])
        if config.tests:
            cmd.extend(config.tests)
        if config.debug:
            cmd.append("--verbose")
        cmd.extend(config.extra_args)
        return CommandSpec(cmd=cmd)


class UnixBenchGenerator(StdoutCommandGenerator):
    """Run UnixBench as a workload generator."""

    tool_name = "UnixBench"

    def __init__(self, config: UnixBenchConfig, name: str = "UnixBenchGenerator"):
        self._command_builder = _UnixBenchCommandBuilder()
        super().__init__(name, config, command_builder=self._command_builder)

    def _build_command(self) -> List[str]:
        return self._command_builder.build(self.config).cmd

    def _command_workdir(self) -> Path | None:
        return self.config.workdir

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



class UnixBenchPlugin(SimpleWorkloadPlugin):
    """Plugin definition for UnixBench."""

    NAME = "unixbench"
    DESCRIPTION = "UnixBench micro-benchmark suite built from source"
    CONFIG_CLS = UnixBenchConfig
    REQUIRED_APT_PACKAGES = [
        "build-essential",
        "libx11-dev",
        "libgl1-mesa-dev",
        "libxext-dev",
        "wget",
    ]
    REQUIRED_LOCAL_TOOLS = ["make", "gcc", "wget"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup.yml"

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

    def get_dockerfile_path(self) -> Optional[Path]:
        path = Path(__file__).parent / "Dockerfile"
        return path if path.exists() else None


PLUGIN = UnixBenchPlugin()
