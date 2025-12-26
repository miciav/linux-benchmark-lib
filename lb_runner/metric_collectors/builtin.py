"""Built-in metric collector plugins shipped with the runner."""

from __future__ import annotations

import importlib
import logging
from typing import Any, List, Optional, Tuple

from lb_runner.metric_collectors.registry import CollectorPlugin
from lb_runner.models.config import BenchmarkConfig

logger = logging.getLogger(__name__)


def _safe_import(module: str, attr: str) -> Tuple[Optional[Any], Optional[Exception]]:
    """Import a module attribute, capturing failures for optional deps."""
    try:
        mod = importlib.import_module(module)
        return getattr(mod, attr), None
    except Exception as exc:  # pragma: no cover - optional deps/environment
        logger.debug("Optional import failed for %s.%s: %s", module, attr, exc)
        return None, exc


PSUtilCollector, PSUTIL_IMPORT_ERROR = _safe_import(
    "lb_runner.metric_collectors.psutil_collector", "PSUtilCollector"
)
PSUTIL_AGGREGATOR, _ = _safe_import(
    "lb_runner.metric_collectors.psutil_collector", "aggregate_psutil"
)

CLICollector, CLI_IMPORT_ERROR = _safe_import(
    "lb_runner.metric_collectors.cli_collector", "CLICollector"
)
CLI_AGGREGATOR, _ = _safe_import(
    "lb_runner.metric_collectors.cli_collector", "aggregate_cli"
)


def _create_psutil(config: BenchmarkConfig) -> PSUtilCollector:
    if PSUtilCollector is None:
        raise RuntimeError(f"PSUtilCollector unavailable: {PSUTIL_IMPORT_ERROR}")
    return PSUtilCollector(
        interval_seconds=config.collectors.psutil_interval
        or config.metrics_interval_seconds
    )


def _create_cli(config: BenchmarkConfig) -> CLICollector:
    if CLICollector is None:
        raise RuntimeError(f"CLICollector unavailable: {CLI_IMPORT_ERROR}")
    return CLICollector(
        interval_seconds=config.metrics_interval_seconds,
        commands=config.collectors.cli_commands,
    )


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


def builtin_collectors() -> List[Any]:
    """Return built-in collector plugins."""
    return [PSUTIL_COLLECTOR, CLI_COLLECTOR]
