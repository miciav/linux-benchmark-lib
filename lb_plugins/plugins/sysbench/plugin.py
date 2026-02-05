"""
Sysbench workload plugin for linux-benchmark-lib.

Provides a CPU-focused sysbench runner with sensible presets for low/medium/high
intensities and optional custom arguments for advanced tuning.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Optional

from pydantic import Field

from ...base_generator import CommandSpec
from ...interface import BasePluginConfig, SimpleWorkloadPlugin, WorkloadIntensity
from ..command_base import StdoutCommandGenerator

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
    rate: int | None = Field(
        default=None, ge=0, description="Optional rate limit (req/s)."
    )
    cpu_max_prime: int = Field(
        default=20000, gt=0, description="Max prime for cpu test."
    )
    extra_args: list[str] = Field(default_factory=list)
    debug: bool = Field(default=False)


class _SysbenchCommandBuilder:
    def build(self, config: SysbenchConfig) -> CommandSpec:
        cmd: List[str] = ["sysbench", config.test]
        cmd.extend(_sysbench_args(config))
        cmd.append("run")
        return CommandSpec(cmd=cmd)


class _SysbenchResultParser:
    def parse(self, result: dict[str, Any]) -> dict[str, Any]:
        stdout = result.get("stdout")
        if not isinstance(stdout, str):
            return result
        _update_float_metric(
            result,
            stdout,
            "events_per_second",
            r"events per second:\\s*([0-9.]+)",
        )
        _update_float_metric(
            result,
            stdout,
            "total_time_seconds",
            r"total time:\\s*([0-9.]+)s",
        )
        return result

    @staticmethod
    def _update_metric(
        result: dict[str, Any],
        stdout: str,
        *,
        key: str,
        pattern: str,
    ) -> None:
        match = re.search(pattern, stdout, re.I)
        if not match:
            return
        try:
            result[key] = float(match.group(1))
        except ValueError:
            return


class SysbenchGenerator(StdoutCommandGenerator):
    """Run sysbench as a workload generator."""

    tool_name = "sysbench"

    def __init__(self, config: SysbenchConfig, name: str = "SysbenchGenerator"):
        self._command_builder = _SysbenchCommandBuilder()
        self._result_parser = _SysbenchResultParser()
        super().__init__(
            name,
            config,
            command_builder=self._command_builder,
            result_parser=self._result_parser,
        )

    def _build_command(self) -> List[str]:
        return self._command_builder.build(self.config).cmd

    def _timeout_seconds(self) -> Optional[int]:
        return max(self.config.time, 0) + self.config.timeout_buffer

    def _validate_environment(self) -> bool:
        if shutil.which("sysbench") is None:
            logger.error("sysbench binary not found in PATH.")
            return False
        return self._check_sysbench_version()

    @staticmethod
    def _check_sysbench_version() -> bool:
        try:
            result = subprocess.run(
                ["sysbench", "--version"], capture_output=True, text=True
            )
            return result.returncode == 0
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to validate sysbench availability: %s", exc)
            return False


class SysbenchPlugin(SimpleWorkloadPlugin):
    """Plugin definition for sysbench."""

    NAME = "sysbench"
    DESCRIPTION = "CPU micro-benchmark via sysbench"
    CONFIG_CLS = SysbenchConfig
    REQUIRED_APT_PACKAGES = ["sysbench"]
    REQUIRED_LOCAL_TOOLS = ["sysbench"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"

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

    def get_dockerfile_path(self) -> Optional[Path]:
        path = Path(__file__).parent / "Dockerfile"
        return path if path.exists() else None

    def get_ansible_teardown_path(self) -> Optional[Path]:
        return None


PLUGIN = SysbenchPlugin()


def _sysbench_args(config: SysbenchConfig) -> list[str]:
    args = [f"--threads={config.threads}", f"--time={config.time}"]
    args.extend(_sysbench_optional_args(config))
    return args


def _sysbench_optional_args(config: SysbenchConfig) -> list[str]:
    args: list[str] = []
    _append_event_arg(args, config)
    _append_rate_arg(args, config)
    _append_cpu_arg(args, config)
    _append_debug_arg(args, config)
    args.extend(config.extra_args)
    return args


def _append_event_arg(args: list[str], config: SysbenchConfig) -> None:
    if config.max_requests is not None:
        args.append(f"--events={config.max_requests}")


def _append_rate_arg(args: list[str], config: SysbenchConfig) -> None:
    if config.rate is not None:
        args.append(f"--rate={config.rate}")


def _append_cpu_arg(args: list[str], config: SysbenchConfig) -> None:
    if config.test == "cpu":
        args.append(f"--cpu-max-prime={config.cpu_max_prime}")


def _append_debug_arg(args: list[str], config: SysbenchConfig) -> None:
    if config.debug:
        args.append("--verbosity=3")


def _update_float_metric(
    result: dict[str, Any],
    stdout: str,
    key: str,
    pattern: str,
) -> None:
    match = re.search(pattern, stdout, re.I)
    if not match:
        return
    try:
        result[key] = float(match.group(1))
    except ValueError:
        return
