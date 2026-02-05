"""Tabular summaries for plugin registries (UI-friendly)."""

from __future__ import annotations

from typing import Dict, Optional

from lb_plugins.registry import PluginRegistry


def build_plugin_table(
    registry: PluginRegistry,
    enabled: Optional[Dict[str, bool]] = None,
) -> tuple[list[str], list[list[str]]]:
    """Return headers and rows representing plugin availability/enabled status."""
    enabled = enabled or {}
    headers = ["Name", "Enabled", "Description"]
    rows = []
    for name, plugin in registry.available().items():
        rows.append(
            [
                name,
                "yes" if enabled.get(name, False) else "no",
                getattr(plugin, "description", "") or "",
            ]
        )
    return headers, rows
