"""
Stress-ng workload generator implementation.

Modular plugin version.
"""

from pathlib import Path
from typing import List, Optional

from pydantic import Field

from ...base_generator import CommandSpec
from ...interface import BasePluginConfig, SimpleWorkloadPlugin, WorkloadIntensity
from ..command_base import StdoutCommandGenerator


class StressNGConfig(BasePluginConfig):
    """Configuration for stress-ng workload generator."""

    cpu_workers: int = Field(
        default=0, ge=0, description="0 means use all available CPUs"
    )
    cpu_method: str = Field(
        default="all", description="CPU stress method"
    )
    vm_workers: int = Field(
        default=1, ge=0, description="Virtual memory workers"
    )
    vm_bytes: str = Field(
        default="1G", description="Memory per VM worker"
    )
    io_workers: int = Field(
        default=1, ge=0, description="I/O workers"
    )
    timeout: int = Field(default=60, gt=0, description="Timeout in seconds")
    metrics_brief: bool = Field(
        default=True, description="Use brief metrics output"
    )
    extra_args: List[str] = Field(
        default_factory=list, description="Additional stress-ng arguments"
    )
    debug: bool = Field(default=False)


class _StressNGCommandBuilder:
    def build(self, config: StressNGConfig) -> CommandSpec:
        cmd = ["stress-ng"]
        if config.cpu_workers > 0:
            cmd.extend(["--cpu", str(config.cpu_workers)])
            cmd.extend(["--cpu-method", config.cpu_method])
        if config.vm_workers > 0:
            cmd.extend(["--vm", str(config.vm_workers)])
            cmd.extend(["--vm-bytes", config.vm_bytes])
        if config.io_workers > 0:
            cmd.extend(["--io", str(config.io_workers)])
        cmd.extend(["--timeout", f"{config.timeout}s"])
        if config.metrics_brief:
            cmd.append("--metrics-brief")
        if config.debug:
            cmd.append("--verbose")
        cmd.extend(config.extra_args)
        return CommandSpec(cmd=cmd)


class StressNGGenerator(StdoutCommandGenerator):
    """Workload generator using stress-ng."""

    tool_name = "stress-ng"

    def __init__(self, config: StressNGConfig, name: str = "StressNGGenerator"):
        self._command_builder = _StressNGCommandBuilder()
        super().__init__(name, config, command_builder=self._command_builder)

    def _build_command(self) -> List[str]:
        return self._command_builder.build(self.config).cmd


class StressNGPlugin(SimpleWorkloadPlugin):
    """Plugin definition for StressNG."""

    NAME = "stress_ng"
    DESCRIPTION = "CPU/IO/memory stress via stress-ng"
    CONFIG_CLS = StressNGConfig
    GENERATOR_CLS = StressNGGenerator
    REQUIRED_APT_PACKAGES = ["stress-ng"]
    REQUIRED_LOCAL_TOOLS = ["stress-ng"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"
    TEARDOWN_PLAYBOOK = Path(__file__).parent / "ansible" / "teardown.yml"

    def get_preset_config(
        self, level: WorkloadIntensity
    ) -> Optional[StressNGConfig]:
        if level == WorkloadIntensity.LOW:
            return StressNGConfig(
                cpu_workers=1,
                vm_workers=1,
                vm_bytes="128M",
                io_workers=0,
                timeout=30,
            )
        if level == WorkloadIntensity.MEDIUM:
            return StressNGConfig(
                cpu_workers=0,
                vm_workers=1,
                vm_bytes="50%",
                io_workers=1,
                timeout=60,
                extra_args=["--cpu-load", "50"],
            )
        if level == WorkloadIntensity.HIGH:
            return StressNGConfig(
                cpu_workers=0,
                cpu_method="matrixprod",
                vm_workers=2,
                vm_bytes="90%",
                io_workers=4,
                timeout=120,
            )
        return None


PLUGIN = StressNGPlugin()
