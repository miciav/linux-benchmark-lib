"""Filesystem discovery helpers for user-installed plugins."""

from __future__ import annotations

import importlib.util
import logging
import sys
import tomllib
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


logger = logging.getLogger(__name__)


def load_plugins_from_dir(root: Path, register: Callable[[Any], None]) -> None:
    """Load plugins from a directory if it exists."""
    if not root.exists():
        return
    load_python_files(root, register)
    for path in iter_plugin_dirs(root):
        target = resolve_target_from_dir(path)
        if target:
            module_name = path.name if target.parent == path else target.parent.name
            load_plugin_from_path(target, register, module_name=module_name)
        else:
            logger.debug(
                "Skipping user plugin dir %s: No suitable python entry point found.",
                path,
            )


def load_python_files(root: Path, register: Callable[[Any], None]) -> None:
    """Load top-level python modules that export PLUGIN/PLUGINS."""
    for path in root.glob("*.py"):
        if path.name.startswith("_"):
            continue
        load_plugin_from_path(path, register)


def iter_plugin_dirs(root: Path) -> Iterable[Path]:
    """Yield plugin directory candidates under root."""
    return (
        path
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    )


def resolve_target_from_dir(path: Path) -> Optional[Path]:
    """Resolve a plugin entry point within a plugin directory."""
    toml_file = path / "pyproject.toml"
    if toml_file.exists():
        target = resolve_entry_point_from_toml(path, toml_file)
        if target:
            logger.debug("Resolved plugin via pyproject.toml: %s", target)
            return target
    for candidate in candidate_entrypoints(path):
        if candidate.exists():
            return candidate
    return None


def candidate_entrypoints(path: Path) -> Iterable[Path]:
    """Return likely plugin module paths in a plugin directory."""
    candidates = [
        path / "__init__.py",
        path / "plugin.py",
        path / f"{path.name}.py",
    ]
    for sub in path.iterdir():
        if sub.is_dir() and not sub.name.startswith((".", "_", "tests")):
            candidates.append(sub / "plugin.py")
            candidates.append(sub / "__init__.py")
    return candidates


def resolve_entry_point_from_toml(root: Path, toml_path: Path) -> Optional[Path]:
    """Parse pyproject.toml to guess the package location."""
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)

        project = data.get("project", {})
        name = project.get("name")
        if name:
            pkg_name = name.replace("-", "_")
            src_pkg = root / "src" / pkg_name
            if src_pkg.exists():
                return (
                    src_pkg / "plugin.py"
                    if (src_pkg / "plugin.py").exists()
                    else src_pkg / "__init__.py"
                )

            root_pkg = root / pkg_name
            if root_pkg.exists():
                return (
                    root_pkg / "plugin.py"
                    if (root_pkg / "plugin.py").exists()
                    else root_pkg / "__init__.py"
                )

    except Exception as exc:
        logger.warning("Failed to parse %s: %s", toml_path, exc)
    return None


def load_plugin_from_path(
    path: Path,
    register: Callable[[Any], None],
    module_name: Optional[str] = None,
) -> None:
    try:
        name = module_name or path.stem
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                logger.error("Error executing module %s: %s", path, exc)
                return

            register_from_module(module, register, source=str(path))
    except Exception as exc:
        logger.warning("Failed to load user plugin %s: %s", path, exc)


def register_from_module(
    module: Any,
    register: Callable[[Any], None],
    source: str,
) -> None:
    """Register PLUGIN / PLUGINS / get_plugins() exports from a python module."""
    try:
        if hasattr(module, "get_plugins") and callable(getattr(module, "get_plugins")):
            discovered = module.get_plugins()
            candidates = discovered if isinstance(discovered, list) else [discovered]
        elif hasattr(module, "PLUGINS"):
            discovered = getattr(module, "PLUGINS")
            candidates = discovered if isinstance(discovered, list) else [discovered]
        elif hasattr(module, "PLUGIN"):
            candidates = [getattr(module, "PLUGIN")]
        else:
            logger.debug(
                "Skipping %s: no PLUGIN/PLUGINS/get_plugins exports found", source
            )
            return

        registered = 0
        for plugin in candidates:
            if plugin is None:
                continue
            register(plugin)
            registered += 1
        if registered:
            logger.info("Loaded %s plugin(s) from %s", registered, source)
        else:
            logger.debug("Skipping %s: exported plugin list was empty", source)
    except Exception as exc:
        logger.warning("Failed to register plugins from %s: %s", source, exc)
