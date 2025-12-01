"""Built-in workload plugins shipped with the library."""

import importlib
import logging
import pkgutil
import sys
from pathlib import Path
from typing import List, Any, Optional, Tuple, Callable, Dict

from ..benchmark_config import BenchmarkConfig

# Import the registry types
from .registry import CollectorPlugin

logger = logging.getLogger(__name__)
_PACKAGE_ROOT = __package__.rsplit(".", 1)[0]

# --- Collector Factories ---

def _safe_import(module: str, attr: str) -> Tuple[Optional[Any], Optional[Exception]]:
    """Import a module attribute, capturing failures for optional deps."""
    try:
        mod = importlib.import_module(module)
        return getattr(mod, attr), None
    except Exception as exc:  # pragma: no cover - optional deps/environment
        logger.debug("Optional import failed for %s.%s: %s", module, attr, exc)
        return None, exc

PSUtilCollector, PSUTIL_IMPORT_ERROR = _safe_import(f"{_PACKAGE_ROOT}.metric_collectors.psutil_collector", "PSUtilCollector")
PSUTIL_AGGREGATOR, _ = _safe_import(f"{_PACKAGE_ROOT}.metric_collectors.psutil_collector", "aggregate_psutil")

CLICollector, CLI_IMPORT_ERROR = _safe_import(f"{_PACKAGE_ROOT}.metric_collectors.cli_collector", "CLICollector")
CLI_AGGREGATOR, _ = _safe_import(f"{_PACKAGE_ROOT}.metric_collectors.cli_collector", "aggregate_cli")

PerfCollector, PERF_IMPORT_ERROR = _safe_import(f"{_PACKAGE_ROOT}.metric_collectors.perf_collector", "PerfCollector")
PERF_AGGREGATOR, _ = _safe_import(f"{_PACKAGE_ROOT}.metric_collectors.perf_collector", "aggregate_perf")

EBPFCollector, EBPF_IMPORT_ERROR = _safe_import(f"{_PACKAGE_ROOT}.metric_collectors.ebpf_collector", "EBPFCollector")
EBPF_AGGREGATOR, _ = _safe_import(f"{_PACKAGE_ROOT}.metric_collectors.ebpf_collector", "aggregate_ebpf")

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
    aggregator=PSUTIL_AGGREGATOR,
    should_run=lambda cfg: True,
)

CLI_COLLECTOR = CollectorPlugin(
    name="CLICollector",
    description="Metrics via CLI commands",
    factory=_create_cli,
    aggregator=CLI_AGGREGATOR,
    should_run=lambda cfg: bool(cfg.collectors.cli_commands),
)

PERF_COLLECTOR = CollectorPlugin(
    name="PerfCollector",
    description="Hardware events via perf",
    factory=_create_perf,
    aggregator=PERF_AGGREGATOR,
    should_run=lambda cfg: bool(cfg.collectors.perf_config.events),
)

EBPF_COLLECTOR = CollectorPlugin(
    name="EBPFCollector",
    description="Kernel tracing via eBPF",
    factory=_create_ebpf,
    aggregator=EBPF_AGGREGATOR,
    should_run=lambda cfg: cfg.collectors.enable_ebpf,
)


def builtin_plugins() -> List[Any]:
    """
    Return built-in workload and collector plugins via dynamic discovery.
    Scans `plugins/` for `PLUGIN` exports.
    """
    plugins = [
        PSUTIL_COLLECTOR,
        CLI_COLLECTOR,
        PERF_COLLECTOR,
        EBPF_COLLECTOR,
    ]

    # 1. Scan plugins/*/plugin.py
    plugins_path = Path(__file__).parent
    if plugins_path.exists():
        for item in plugins_path.iterdir():
            if item.is_dir() and (item / "plugin.py").exists():
                module_name = f"{__package__}.{item.name}.plugin"
                try:
                    mod = importlib.import_module(module_name)
                    if hasattr(mod, "PLUGIN"):
                        plugins.append(mod.PLUGIN)
                except ImportError as e:
                    logger.debug(f"Skipping plugin {module_name}: {e}")

    return plugins
