"""Built-in workload plugins shipped with the library."""

from typing import List, Any, Optional, Tuple, Callable
import importlib
import logging

from benchmark_config import BenchmarkConfig, DDConfig, FIOConfig, IPerf3Config, Top500Config

# Import the registry types
from .registry import LegacyWorkloadPlugin, CollectorPlugin

# Import Refactored Plugins
from workload_generators.stress_ng_generator import PLUGIN as STRESS_NG_PLUGIN
from workload_generators.geekbench_generator import PLUGIN as GEEKBENCH_PLUGIN
from workload_generators.sysbench_generator import PLUGIN as SYSBENCH_PLUGIN


logger = logging.getLogger(__name__)


def _safe_import(module: str, attr: str) -> Tuple[Optional[Any], Optional[Exception]]:
    """Import a module attribute, capturing failures for optional deps."""
    try:
        mod = importlib.import_module(module)
        return getattr(mod, attr), None
    except Exception as exc:  # pragma: no cover - optional deps/environment
        logger.debug("Optional import failed for %s.%s: %s", module, attr, exc)
        return None, exc


DDGenerator, DD_IMPORT_ERROR = _safe_import("workload_generators.dd_generator", "DDGenerator")
FIOGenerator, FIO_IMPORT_ERROR = _safe_import("workload_generators.fio_generator", "FIOGenerator")
IPerf3Generator, IPERF3_IMPORT_ERROR = _safe_import("workload_generators.iperf3_generator", "IPerf3Generator")
Top500Generator, TOP500_IMPORT_ERROR = _safe_import("workload_generators.top500_generator", "Top500Generator")
PSUtilCollector, PSUTIL_IMPORT_ERROR = _safe_import("metric_collectors.psutil_collector", "PSUtilCollector")
CLICollector, CLI_IMPORT_ERROR = _safe_import("metric_collectors.cli_collector", "CLICollector")
PerfCollector, PERF_IMPORT_ERROR = _safe_import("metric_collectors.perf_collector", "PerfCollector")
EBPFCollector, EBPF_IMPORT_ERROR = _safe_import("metric_collectors.ebpf_collector", "EBPFCollector")


def _make_factory(generator_cls: Optional[Any], error: Optional[Exception], label: str) -> Callable[[Any], Any]:
    """Create a factory that raises a helpful error when a generator is missing."""
    def _factory(config: Any) -> Any:
        if generator_cls is None:
            raise RuntimeError(f"{label} generator unavailable: {error}")
        return generator_cls(config)
    return _factory


# --- Legacy Plugins (To Be Refactored) ---

IPERF3_PLUGIN = LegacyWorkloadPlugin(
    name="iperf3",
    description="Network throughput via iperf3 client",
    config_cls=IPerf3Config,
    factory=_make_factory(IPerf3Generator, IPERF3_IMPORT_ERROR, "iperf3"),
)

DD_PLUGIN = LegacyWorkloadPlugin(
    name="dd",
    description="Sequential disk I/O via dd",
    config_cls=DDConfig,
    factory=_make_factory(DDGenerator, DD_IMPORT_ERROR, "dd"),
)

FIO_PLUGIN = LegacyWorkloadPlugin(
    name="fio",
    description="Flexible disk I/O via fio",
    config_cls=FIOConfig,
    factory=_make_factory(FIOGenerator, FIO_IMPORT_ERROR, "fio"),
)

TOP500_PLUGIN = LegacyWorkloadPlugin(
    name="top500",
    description="HPL Linpack via geerlingguy/top500-benchmark playbook",
    config_cls=Top500Config,
    factory=_make_factory(Top500Generator, TOP500_IMPORT_ERROR, "top500"),
)


# --- Collector Factories ---

def _create_psutil(config: BenchmarkConfig) -> PSUtilCollector:
    if PSUtilCollector is None:
        raise RuntimeError(f"PSUtilCollector unavailable: {PSUTIL_IMPORT_ERROR}")
    return PSUtilCollector(
        interval_seconds=config.collectors.psutil_interval or config.metrics_interval_seconds
    )

def _create_cli(config: BenchmarkConfig) -> CLICollector:
    if CLICollector is None:
        raise RuntimeError(f"CLICollector unavailable: {CLI_IMPORT_ERROR}")
    return CLICollector(
        interval_seconds=config.metrics_interval_seconds,
        commands=config.collectors.cli_commands
    )

def _create_perf(config: BenchmarkConfig) -> PerfCollector:
    if PerfCollector is None:
        raise RuntimeError(f"PerfCollector unavailable: {PERF_IMPORT_ERROR}")
    return PerfCollector(
        interval_seconds=config.metrics_interval_seconds,
        events=config.collectors.perf_config.events
    )

def _create_ebpf(config: BenchmarkConfig) -> EBPFCollector:
    if EBPFCollector is None:
        raise RuntimeError(f"EBPFCollector unavailable: {EBPF_IMPORT_ERROR}")
    return EBPFCollector(
        interval_seconds=config.metrics_interval_seconds
    )

# --- Collector Plugins ---

PSUTIL_COLLECTOR = CollectorPlugin(
    name="PSUtilCollector",
    description="System metrics via psutil",
    factory=_create_psutil,
    should_run=lambda cfg: True,
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


def builtin_plugins() -> List[Any]:
    """Return built-in workload and collector plugins."""
    return [
        STRESS_NG_PLUGIN,
        IPERF3_PLUGIN,
        DD_PLUGIN,
        FIO_PLUGIN,
        TOP500_PLUGIN,
        GEEKBENCH_PLUGIN,
        SYSBENCH_PLUGIN,
        PSUTIL_COLLECTOR,
        CLI_COLLECTOR,
        PERF_COLLECTOR,
        EBPF_COLLECTOR,
    ]
