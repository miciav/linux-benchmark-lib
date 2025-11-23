"""Built-in workload plugins shipped with the library."""

from typing import List

from benchmark_config import BenchmarkConfig, DDConfig, FIOConfig, IPerf3Config, StressNGConfig, Top500Config
from workload_generators import DDGenerator, FIOGenerator, IPerf3Generator, StressNGGenerator, Top500Generator
from metric_collectors import CLICollector, EBPFCollector, PSUtilCollector, PerfCollector

from .registry import WorkloadPlugin, CollectorPlugin


STRESS_NG_PLUGIN = WorkloadPlugin(
    name="stress_ng",
    description="CPU/IO/memory stress via stress-ng",
    config_cls=StressNGConfig,
    factory=StressNGGenerator,
)

IPERF3_PLUGIN = WorkloadPlugin(
    name="iperf3",
    description="Network throughput via iperf3 client",
    config_cls=IPerf3Config,
    factory=IPerf3Generator,
)

DD_PLUGIN = WorkloadPlugin(
    name="dd",
    description="Sequential disk I/O via dd",
    config_cls=DDConfig,
    factory=DDGenerator,
)

FIO_PLUGIN = WorkloadPlugin(
    name="fio",
    description="Flexible disk I/O via fio",
    config_cls=FIOConfig,
    factory=FIOGenerator,
)

TOP500_PLUGIN = WorkloadPlugin(
    name="top500",
    description="HPL Linpack via geerlingguy/top500-benchmark playbook",
    config_cls=Top500Config,
    factory=Top500Generator,
)


# --- Collector Factories ---

def _create_psutil(config: BenchmarkConfig) -> PSUtilCollector:
    return PSUtilCollector(
        interval_seconds=config.collectors.psutil_interval or config.metrics_interval_seconds
    )


def _create_cli(config: BenchmarkConfig) -> CLICollector:
    return CLICollector(
        interval_seconds=config.metrics_interval_seconds,
        commands=config.collectors.cli_commands
    )


def _create_perf(config: BenchmarkConfig) -> PerfCollector:
    return PerfCollector(
        interval_seconds=config.metrics_interval_seconds,
        events=config.collectors.perf_config.events
    )


def _create_ebpf(config: BenchmarkConfig) -> EBPFCollector:
    return EBPFCollector(
        interval_seconds=config.metrics_interval_seconds
    )


# --- Collector Plugins ---

PSUTIL_COLLECTOR = CollectorPlugin(
    name="PSUtilCollector",
    description="System metrics via psutil",
    factory=_create_psutil,
    should_run=lambda cfg: True,  # Always enabled by default
)

CLI_COLLECTOR = CollectorPlugin(
    name="CLICollector",
    description="Metrics via CLI commands",
    factory=_create_cli,
    should_run=lambda cfg: bool(cfg.collectors.cli_commands),
)

PERF_COLLECTOR = CollectorPlugin(
    name="PerfCollector",
    description="Hardware events via perf",
    factory=_create_perf,
    should_run=lambda cfg: bool(cfg.collectors.perf_config.events),
)

EBPF_COLLECTOR = CollectorPlugin(
    name="EBPFCollector",
    description="Kernel tracing via eBPF",
    factory=_create_ebpf,
    should_run=lambda cfg: cfg.collectors.enable_ebpf,
)


def builtin_plugins() -> List[WorkloadPlugin | CollectorPlugin]:
    """Return built-in workload and collector plugins."""
    return [
        STRESS_NG_PLUGIN,
        IPERF3_PLUGIN,
        DD_PLUGIN,
        FIO_PLUGIN,
        TOP500_PLUGIN,
        PSUTIL_COLLECTOR,
        CLI_COLLECTOR,
        PERF_COLLECTOR,
        EBPF_COLLECTOR,
    ]
