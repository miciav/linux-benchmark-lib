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

    for item in _plugin_dirs(plugins_path):
        module_name = f"{_PLUGIN_PACKAGE}.{item.name}.plugin"
        try:
            plugins.extend(_collect_module_plugins(module_name))
        except ImportError as exc:
            logger.debug("Skipping plugin %s: %s", module_name, exc)

    return plugins


def _plugin_dirs(root: Path) -> List[Path]:
    return [
        item
        for item in root.iterdir()
        if item.is_dir() and (item / "plugin.py").exists()
    ]


def _collect_module_plugins(module_name: str) -> List[Any]:
    mod = importlib.import_module(module_name)
    if hasattr(mod, "get_plugins") and callable(getattr(mod, "get_plugins")):
        return _normalize_plugins(mod.get_plugins())
    if hasattr(mod, "PLUGINS"):
        return _normalize_plugins(getattr(mod, "PLUGINS"))
    if hasattr(mod, "PLUGIN"):
        return [mod.PLUGIN]
    return []


def _normalize_plugins(discovered: Any) -> List[Any]:
    if isinstance(discovered, list):
        return discovered
    return [discovered]
