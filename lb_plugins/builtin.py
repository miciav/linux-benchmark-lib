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
            except ImportError as exc:
                logger.debug("Skipping plugin %s: %s", module_name, exc)

    return plugins
