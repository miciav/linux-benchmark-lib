"""Workload plugin implementations (dd, fio, stress_ng, hpl, stream)."""

from pathlib import Path
from pkgutil import extend_path

__all__: list[str] = []

__path__ = extend_path(__path__, __name__)

try:
    import lb_plugins  # type: ignore

    plugin_root = Path(lb_plugins.__file__).resolve().parent / "plugins"
    if plugin_root.exists():
        __path__.append(str(plugin_root))
except Exception:
    pass
