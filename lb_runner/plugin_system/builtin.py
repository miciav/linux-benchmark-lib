"""Built-in workload plugins shipped with the library."""

import importlib
import logging
from pathlib import Path
from typing import List, Any, Optional, Tuple, Callable

from lb_runner.models.config import BenchmarkConfig

# Import the registry types
from .registry import CollectorPlugin

logger = logging.getLogger(__name__)
_PACKAGE_ROOT = __package__.rsplit(".", 1)[0]
_PLUGIN_PACKAGE = f"{_PACKAGE_ROOT}.plugins"

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


def builtin_plugins() -> List[Any]:
    """
    Return built-in workload and collector plugins via dynamic discovery.
    Scans `plugins/` for `PLUGIN` exports.
    """
    plugins = [
        PSUTIL_COLLECTOR,
        CLI_COLLECTOR,
    ]

    # 1. Scan plugins/*/plugin.py
    plugins_path = Path(__file__).resolve().parent.parent / "plugins"
    if plugins_path.exists():
        for item in plugins_path.iterdir():
            if item.is_dir() and (item / "plugin.py").exists():
                module_name = f"{_PLUGIN_PACKAGE}.{item.name}.plugin"
                try:
                    mod = importlib.import_module(module_name)
                    if hasattr(mod, "get_plugins") and callable(getattr(mod, "get_plugins")):
                        discovered = mod.get_plugins()
                        if isinstance(discovered, list):
                            plugins.extend(discovered)
                        else:
                            plugins.append(discovered)
                    elif hasattr(mod, "PLUGINS"):
                        discovered = getattr(mod, "PLUGINS")
                        if isinstance(discovered, list):
                            plugins.extend(discovered)
                        else:
                            plugins.append(discovered)
                    elif hasattr(mod, "PLUGIN"):
                        plugins.append(mod.PLUGIN)
                except ImportError as e:
                    logger.debug(f"Skipping plugin {module_name}: {e}")

    return plugins
