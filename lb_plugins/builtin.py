"""Built-in workload plugins shipped with the library."""

import importlib
import logging
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)
_PLUGIN_PACKAGE = f"{__package__}.plugins"


def builtin_plugins() -> List[Any]:
    """
    Return built-in workload plugins via dynamic discovery.

    Scans `plugins/` for `PLUGIN`, `PLUGINS`, or `get_plugins` exports.
    """
    plugins: List[Any] = []
    plugins_path = Path(__file__).resolve().parent / "plugins"
    if not plugins_path.exists():
        return plugins

    for module_name in _iter_plugin_modules(plugins_path):
        try:
            mod = importlib.import_module(module_name)
        except ImportError as exc:
            logger.debug("Skipping plugin %s: %s", module_name, exc)
            continue
        plugins.extend(_extract_plugins(mod))

    return plugins


def _iter_plugin_modules(plugins_path: Path) -> List[str]:
    modules: List[str] = []
    for item in plugins_path.iterdir():
        if item.is_dir() and (item / "plugin.py").exists():
            modules.append(f"{_PLUGIN_PACKAGE}.{item.name}.plugin")
    return modules


def _extract_plugins(module: Any) -> List[Any]:
    getter = getattr(module, "get_plugins", None)
    if callable(getter):
        return _normalize_plugins(getter())
    if hasattr(module, "PLUGINS"):
        return _normalize_plugins(getattr(module, "PLUGINS"))
    if hasattr(module, "PLUGIN"):
        return [module.PLUGIN]
    return []


def _normalize_plugins(discovered: Any) -> List[Any]:
    if isinstance(discovered, list):
        return discovered
    return [discovered]
