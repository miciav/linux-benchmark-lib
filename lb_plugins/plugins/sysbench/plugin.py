"""
Sysbench workload plugin for linux-benchmark-lib.

Provides a CPU-focused sysbench runner with sensible presets for low/medium/high
intensities and optional custom arguments for advanced tuning.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Optional, Type

from pydantic import Field

from ...base_generator import CommandGenerator
from ...interface import BasePluginConfig, WorkloadIntensity, WorkloadPlugin

logger = logging.getLogger(__name__)


class SysbenchConfig(BasePluginConfig):
    """Configuration for sysbench CPU workload."""

    test: str = Field(
        default="cpu",
        description="Sysbench test type (currently optimized for cpu).",
    )
    threads: int = Field(default=1, gt=0)
    time: int = Field(default=60, gt=0, description="Runtime in seconds.")
    max_requests: int | None = Field(
        default=None,
        gt=0,
        description="Number of events; when None runs for `time` seconds.",
    )
    rate: int | None = Field(default=None, ge=0, description="Optional rate limit (req/s).")
    cpu_max_prime: int = Field(default=20000, gt=0, description="Max prime for cpu test.")
    extra_args: list[str] = Field(default_factory=list)
    debug: bool = Field(default=False)


class SysbenchGenerator(CommandGenerator):
    """Run sysbench as a workload generator."""

    def __init__(self, config: SysbenchConfig, name: str = "SysbenchGenerator"):
        super().__init__(name, config)

    def _build_command(self) -> List[str]:
        cmd: List[str] = ["sysbench", self.config.test]
        cmd.append(f"--threads={self.config.threads}")
        cmd.append(f"--time={self.config.time}")
        if self.config.max_requests is not None:
            cmd.append(f"--events={self.config.max_requests}")
        if self.config.rate is not None:
            cmd.append(f"--rate={self.config.rate}")
        if self.config.test == "cpu":
            cmd.append(f"--cpu-max-prime={self.config.cpu_max_prime}")
        if self.config.debug:
            cmd.append("--verbosity=3")
        cmd.extend(self.config.extra_args)
        cmd.append("run")
        return cmd

    def _popen_kwargs(self) -> dict[str, Any]:
        return {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
        }

    def _timeout_seconds(self) -> Optional[int]:
        return max(self.config.time, 0) + self.config.timeout_buffer

    def _validate_environment(self) -> bool:
        if shutil.which("sysbench") is None:
            logger.error("sysbench binary not found in PATH.")
            return False
        try:
            result = subprocess.run(
                ["sysbench", "--version"], capture_output=True, text=True
            )
            return result.returncode == 0
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to validate sysbench availability: %s", exc)
            return False

    def _log_failure(
        self, returncode: int, stdout: str, stderr: str, cmd: list[str]
    ) -> None:
        output = stdout or stderr
        if output:
            logger.error("sysbench failed with return code %s: %s", returncode, output)
        else:
            logger.error("sysbench failed with return code %s", returncode)


class SysbenchPlugin(WorkloadPlugin):
    """Plugin definition for sysbench."""

    @property
    def name(self) -> str:
        return "sysbench"

    @property
    def description(self) -> str:
        return "CPU micro-benchmark via sysbench"

    @property
    def config_cls(self) -> Type[SysbenchConfig]:
        return SysbenchConfig

    def create_generator(self, config: SysbenchConfig | dict) -> SysbenchGenerator:
        if isinstance(config, dict):
            config = SysbenchConfig(**config)
        return SysbenchGenerator(config)

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[SysbenchConfig]:
        cpu_count = os.cpu_count() or 2
        if level == WorkloadIntensity.LOW:
            return SysbenchConfig(
                threads=1,
                time=30,
                cpu_max_prime=20000,
            )
        if level == WorkloadIntensity.MEDIUM:
            return SysbenchConfig(
                threads=max(2, cpu_count // 2),
                time=60,
                cpu_max_prime=40000,
            )
        if level == WorkloadIntensity.HIGH:
            return SysbenchConfig(
                threads=max(2, cpu_count),
                time=120,
                cpu_max_prime=80000,
            )
        return None

    def get_required_apt_packages(self) -> List[str]:
        return ["sysbench"]

    def get_required_local_tools(self) -> List[str]:
        return ["sysbench"]

    def get_dockerfile_path(self) -> Optional[Path]:
        path = Path(__file__).parent / "Dockerfile"
        return path if path.exists() else None

    def get_ansible_setup_path(self) -> Optional[Path]:
        path = Path(__file__).parent / "ansible" / "setup.yml"
        return path if path.exists() else None

    def get_ansible_teardown_path(self) -> Optional[Path]:
        return None


PLUGIN = SysbenchPlugin()
