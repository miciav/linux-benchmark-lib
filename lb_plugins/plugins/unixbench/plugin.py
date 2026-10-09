"""UnixBench workload plugin for linux-benchmark-lib.

Builds and runs UnixBench from source (Ubuntu package is outdated/broken).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, ClassVar

from pydantic import Field

from lb_common.api import DatasetDescriptor, MetricSpec
from lb_plugins.base_generator import CommandSpec
from lb_plugins.datasets import plugin_csv_dataset
from lb_plugins.interface import (
    BasePluginConfig,
    SimpleWorkloadPlugin,
    WorkloadIntensity,
)
from lb_plugins.plugins.command_base import StdoutCommandGenerator

logger = logging.getLogger(__name__)


class UnixBenchConfig(BasePluginConfig):
    """Configuration for UnixBench workload."""

    threads: int = Field(default=1, gt=0, description="Passed as -c to Run.")
    iterations: int = Field(default=1, gt=0, description="Passed as -i to Run.")
    tests: list[str] = Field(
        default_factory=list,
        description="If empty, run default suite.",
    )
    workdir: Path = Field(
        default=Path("/opt/UnixBench"),
        description="Where Run lives.",
    )
    extra_args: list[str] = Field(default_factory=list)
    debug: bool = Field(default=False)


class _UnixBenchCommandBuilder:
    def build(self, config: UnixBenchConfig) -> CommandSpec:
        cmd: list[str] = ["./Run"]
        cmd.extend(["-c", str(config.threads)])
        cmd.extend(["-i", str(config.iterations)])
        if config.tests:
            cmd.extend(config.tests)
        if config.debug:
            cmd.append("--verbose")
        cmd.extend(config.extra_args)
        return CommandSpec(cmd=cmd)


# Per-test result line, e.g. "<test name>  77592446.5 lps  (10.0 s, 1 samples)".
_RAW_RESULT = re.compile(
    r"^(\S.*?)\s{2,}([0-9.]+) (\S+)\s+\([0-9.]+ s, \d+ samples\)$", re.M
)
# Rows of the "System Benchmarks [Partial ]Index  BASELINE  RESULT  INDEX" table.
_INDEX_ROW = re.compile(r"^(\S.*?)\s{2,}[0-9.]+\s+[0-9.]+\s+([0-9.]+)$", re.M)
_INDEX_SCORE = re.compile(r"^System Benchmarks Index Score.*?([0-9.]+)\s*$", re.M)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class _UnixBenchResultParser:
    """Lift per-test results, index values and the index score out of stdout."""

    def parse(self, result: dict[str, Any]) -> dict[str, Any]:
        stdout = result.get("stdout")
        if not isinstance(stdout, str):
            return result
        for name, value, unit in _RAW_RESULT.findall(stdout):
            result[f"{_slug(name)}_result"] = float(value)
            result[f"{_slug(name)}_unit"] = unit
        table = stdout.split("BASELINE", 1)[1] if "BASELINE" in stdout else ""
        for name, index in _INDEX_ROW.findall(table):
            result[f"{_slug(name)}_index"] = float(index)
        if score := _INDEX_SCORE.search(stdout):
            result["index_score"] = float(score.group(1))
        return result


class UnixBenchGenerator(StdoutCommandGenerator):
    """Run UnixBench as a workload generator."""

    tool_name = "UnixBench"

    def __init__(self, config: UnixBenchConfig, name: str = "UnixBenchGenerator"):
        self._command_builder = _UnixBenchCommandBuilder()
        super().__init__(
            name,
            config,
            command_builder=self._command_builder,
            result_parser=_UnixBenchResultParser(),
        )
        self.config: UnixBenchConfig = config

    def _build_command(self) -> list[str]:
        assert self._command_builder is not None
        return self._command_builder.build(self.config).cmd

    def _command_workdir(self) -> Path | None:
        return self.config.workdir

    def _timeout_seconds(self) -> int | None:
        return int(self.config.timeout_buffer) + max(
            120, 60 * int(self.config.iterations)
        )

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
    REQUIRED_APT_PACKAGES: ClassVar[list[str]] = [
        "build-essential",
        "libx11-dev",
        "libgl1-mesa-dev",
        "libxext-dev",
        "wget",
    ]
    REQUIRED_LOCAL_TOOLS: ClassVar[list[str]] = ["make", "gcc", "wget"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"

    def describe_datasets(
        self, output_dir: Path, test_name: str
    ) -> list[DatasetDescriptor]:
        return [
            plugin_csv_dataset(
                test_name,
                metrics=[
                    MetricSpec(
                        pattern=r"^generator_(?P<test>.+)_(?P<metric>result)$",
                        unit_column="generator_{test}_unit",
                    ),
                    MetricSpec(
                        pattern=r"^generator_(?P<test>.+)_(?P<metric>index)$",
                        unit="index",
                    ),
                    MetricSpec(
                        column="generator_index_score", name="index_score", unit="index"
                    ),
                ],
            )
        ]

    def create_generator(
        self, config: BasePluginConfig | dict[str, Any]
    ) -> UnixBenchGenerator:
        if isinstance(config, UnixBenchConfig):
            return UnixBenchGenerator(config)
        if isinstance(config, dict):
            return UnixBenchGenerator(UnixBenchConfig(**config))
        return UnixBenchGenerator(UnixBenchConfig(**config.model_dump()))

    def get_preset_config(self, level: WorkloadIntensity) -> UnixBenchConfig | None:
        cpu_count = os.cpu_count() or 2
        if level == WorkloadIntensity.LOW:
            return UnixBenchConfig(threads=1, iterations=1)
        if level == WorkloadIntensity.MEDIUM:
            return UnixBenchConfig(threads=max(2, cpu_count // 2), iterations=1)
        if level == WorkloadIntensity.HIGH:
            return UnixBenchConfig(threads=max(2, cpu_count), iterations=2)
        return None

    def get_dockerfile_path(self) -> Path | None:
        path = Path(__file__).parent / "Dockerfile"
        return path if path.exists() else None


PLUGIN = UnixBenchPlugin()
