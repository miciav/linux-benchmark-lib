"""Discovery helpers for workload plugins."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lb_common.api import (
    discover_entrypoints,
    load_entrypoint,
    load_pending_entrypoints,
)
from lb_plugins.user_plugins import load_plugins_from_dir

logger = logging.getLogger(__name__)
ENTRYPOINT_GROUP = "linux_benchmark.workloads"
BUILTIN_PLUGIN_ROOT = Path(__file__).resolve().parent / "plugins"


def resolve_user_plugin_dir() -> Path:
    """Determine where third-party/user plugins should be installed and loaded from.

    Preference order:
    1) `LB_USER_PLUGIN_DIR` env override (if set).
    2) `<package>/plugins/_user` (portable with runner tree).
    """
    override = os.environ.get("LB_USER_PLUGIN_DIR")
    if override:
        path = Path(override).expanduser().resolve()
        with contextlib.suppress(Exception):
            # Directory creation may fail for read-only locations; caller handles.
            path.mkdir(parents=True, exist_ok=True)
        return path

    candidate = BUILTIN_PLUGIN_ROOT / "_user"
    with contextlib.suppress(Exception):
        candidate.mkdir(parents=True, exist_ok=True)
    return candidate


USER_PLUGIN_DIR = resolve_user_plugin_dir()


def discover_entrypoint_plugins() -> dict[str, Any]:
    """Collect entry points without importing them. Loaded on demand."""
    return discover_entrypoints([ENTRYPOINT_GROUP])


def load_pending_entrypoint_plugins(
    pending: dict[str, Any], register: Callable[[Any], None]
) -> None:
    """Load all pending entry-point plugins."""
    load_pending_entrypoints(pending, register, label="plugin entry point")


def load_entrypoint_plugin(entry_point: Any, register: Callable[[Any], None]) -> None:
    """Load a single entry-point plugin."""
    load_entrypoint(entry_point, register, label="plugin entry point")


def load_user_plugins(
    register: Callable[[Any], None], root: Path | None = None
) -> None:
    """Load plugins from the user plugin directory."""
    load_plugins_from_dir(root or resolve_user_plugin_dir(), register)
