"""Entry-point discovery and loading helpers shared across registries."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any, Callable, Iterable


logger = logging.getLogger(__name__)


def discover_entrypoints(
    groups: Iterable[str],
) -> dict[str, importlib.metadata.EntryPoint]:
    """Collect entry points without importing them. Loaded on demand."""
    pending: dict[str, importlib.metadata.EntryPoint] = {}
    for group in groups:
        try:
            eps = importlib.metadata.entry_points().select(group=group)
        except Exception as exc:
            logger.debug("Failed to read entry points for group %s: %s", group, exc)
            eps = ()
        for entry_point in eps:
            pending.setdefault(entry_point.name, entry_point)
    return pending


def load_entrypoint(
    entry_point: importlib.metadata.EntryPoint,
    register: Callable[[Any], None],
    *,
    label: str = "entry point",
) -> None:
    """Load a single entry-point plugin/collector."""
    try:
        plugin = entry_point.load()
        register(plugin)
    except ImportError as exc:
        logger.debug(
            "Skipping %s %s due to missing dependency: %s", label, entry_point.name, exc
        )
    except Exception as exc:
        logger.warning("Failed to load %s %s: %s", label, entry_point.name, exc)


def load_pending_entrypoints(
    pending: dict[str, importlib.metadata.EntryPoint],
    register: Callable[[Any], None],
    *,
    label: str = "entry point",
) -> None:
    """Load all pending entry-point plugins/collectors."""
    for name in list(pending.keys()):
        entry_point = pending.pop(name, None)
        if not entry_point:
            continue
        load_entrypoint(entry_point, register, label=label)
