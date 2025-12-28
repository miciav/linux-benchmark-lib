"""Filesystem discovery helpers for user-installed plugins."""

from __future__ import annotations

import importlib.util
import types
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
            module_name = _module_name_for_target(path, target)
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
        entry_target = _resolve_project_entrypoint(root, project)
        if entry_target:
            return entry_target
        name = project.get("name") if isinstance(project, dict) else None
        if isinstance(name, str) and name:
            target = _resolve_package_root(root, name)
            if target:
                return target

        tool = data.get("tool", {})
        poetry = tool.get("poetry") if isinstance(tool, dict) else None
        target = _resolve_poetry_entrypoint(root, poetry)
        if target:
            return target

    except Exception as exc:
        logger.warning("Failed to parse %s: %s", toml_path, exc)
    return None


def _resolve_project_entrypoint(root: Path, project: Any) -> Optional[Path]:
    if not isinstance(project, dict):
        return None
    entry_points = project.get("entry-points") or project.get("entry_points")
    if not isinstance(entry_points, dict):
        return None
    workload_group = entry_points.get("linux_benchmark.workloads")
    if not isinstance(workload_group, dict):
        return None
    for value in workload_group.values():
        if isinstance(value, str):
            target = _resolve_entrypoint_module(root, value)
            if target:
                return target
    return None


def _resolve_poetry_entrypoint(root: Path, poetry: Any) -> Optional[Path]:
    if not isinstance(poetry, dict):
        return None
    plugins = poetry.get("plugins")
    if isinstance(plugins, dict):
        workload_group = plugins.get("linux_benchmark.workloads")
        if isinstance(workload_group, dict):
            for value in workload_group.values():
                if isinstance(value, str):
                    target = _resolve_entrypoint_module(root, value)
                    if target:
                        return target
    packages = poetry.get("packages")
    if isinstance(packages, list):
        for entry in packages:
            if not isinstance(entry, dict):
                continue
            include = entry.get("include")
            if not isinstance(include, str) or not include:
                continue
            base = entry.get("from")
            base_path = root / base if isinstance(base, str) and base else root
            target = _resolve_package_path(base_path / include)
            if target:
                return target

    name = poetry.get("name")
    if isinstance(name, str) and name:
        return _resolve_package_root(root, name)
    return None


def _resolve_package_root(root: Path, name: str) -> Optional[Path]:
    pkg_name = name.replace("-", "_")
    for base in (root / "src", root):
        target = _resolve_package_path(base / pkg_name)
        if target:
            return target
    return None


def _resolve_package_path(package_root: Path) -> Optional[Path]:
    plugin_path = package_root / "plugin.py"
    if plugin_path.exists():
        return plugin_path
    init_path = package_root / "__init__.py"
    if init_path.exists():
        return init_path
    return None


def _resolve_entrypoint_module(root: Path, entry_point: str) -> Optional[Path]:
    module_path = entry_point.split(":", 1)[0].strip()
    if not module_path:
        return None
    rel_path = Path(*module_path.split("."))
    for base in (root / "src", root):
        candidate = base / rel_path
        module_file = candidate.with_suffix(".py")
        if module_file.exists():
            return module_file
        if candidate.is_dir():
            plugin_file = candidate / "plugin.py"
            if plugin_file.exists():
                return plugin_file
            init_path = candidate / "__init__.py"
            if init_path.exists():
                return init_path
    return None


def load_plugin_from_path(
    path: Path,
    register: Callable[[Any], None],
    module_name: Optional[str] = None,
) -> None:
    try:
        name = module_name or path.stem
        is_package = path.name == "__init__.py"
        if "." in name:
            _ensure_parent_packages(name, path)
        spec = importlib.util.spec_from_file_location(
            name,
            path,
            submodule_search_locations=[str(path.parent)] if is_package else None,
        )
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


def _module_name_for_target(root: Path, target: Path) -> str:
    base = _module_base_path(root, target)
    rel = target.relative_to(base)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return target.stem
    return ".".join(parts)


def _module_base_path(root: Path, target: Path) -> Path:
    src_root = root / "src"
    try:
        if target.is_relative_to(src_root):
            return src_root
    except AttributeError:
        try:
            target.relative_to(src_root)
            return src_root
        except ValueError:
            pass
    return root


def _ensure_parent_packages(module_name: str, path: Path) -> None:
    parts = module_name.split(".")
    if len(parts) < 2:
        return
    parent_dir = path.parent
    for idx in range(len(parts) - 1, 0, -1):
        pkg_name = ".".join(parts[:idx])
        if pkg_name in sys.modules:
            parent_dir = parent_dir.parent
            continue
        pkg_module = types.ModuleType(pkg_name)
        pkg_module.__path__ = [str(parent_dir)]
        sys.modules[pkg_name] = pkg_module
        parent_dir = parent_dir.parent
