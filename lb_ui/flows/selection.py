"""Workflows for interactive selection of plugins and workloads."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Optional, Set

from lb_controller.api import (
    BenchmarkConfig,
    ConfigService,
    PluginRegistry,
    WorkloadConfig,
    build_plugin_table,
)
from lb_ui.tui.system.protocols import UI
from lb_ui.tui.system.models import PickItem, TableModel


def select_workloads_interactively(
    ui: UI,
    config_service: ConfigService,
    cfg: BenchmarkConfig,
    registry: PluginRegistry,
    config: Optional[Path],
    set_default: bool,
) -> None:
    """Interactively toggle configured workloads using arrows + space."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        ui.present.error("Interactive selection requires a TTY.")
        sys.exit(1)

    available_plugins = registry.available()
    items = []

    intensities_catalog = [
        PickItem(id="user_defined", title="user_defined", description="Custom intensity"),
        PickItem(id="low", title="low", description="Light load"),
        PickItem(id="medium", title="medium", description="Balanced load"),
        PickItem(id="high", title="high", description="Aggressive load"),
    ]

    # Prepare items for picker with variants as intensities
    for name, wl in sorted(cfg.workloads.items()):
        plugin_obj = available_plugins.get(wl.plugin)
        description = getattr(plugin_obj, "description", "") if plugin_obj else ""
        current_intensity = wl.intensity if wl.intensity else "user_defined"
        variant_list = []
        for variant in intensities_catalog:
            label = variant.title
            desc = variant.description
            if variant.id == current_intensity:
                desc = f"(current) {desc}"
            variant_list.append(
                PickItem(
                    id=variant.id,
                    title=label,
                    description=desc,
                    payload=variant.payload,
                    tags=variant.tags,
                    search_blob=variant.search_blob or label,
                    preview=variant.preview,
                )
            )

        item = PickItem(
            id=name,
            title=name,
            description=f"Plugin: {wl.plugin} | Intensity: {current_intensity} | {description}",
            payload=wl,
            variants=variant_list,
            search_blob=f"{name} {wl.plugin} {description}",
        )
        items.append(item)

    selection = ui.picker.pick_many(items, title="Select Configured Workloads")
    selected_names = set()
    intensities: Dict[str, str] = {}

    for picked in selection:
        # Variants come back as "<workload>:<intensity>"
        if ":" in picked.id:
            base, level = picked.id.split(":", 1)
            selected_names.add(base)
            intensities[base] = level
        else:
            selected_names.add(picked.id)

    if not selection:
        ui.present.warning("Selection cancelled or empty.")
        if not ui.form.confirm("Do you want to proceed with NO workloads enabled?", default=False):
            sys.exit(1)

    cfg_write, target, stale, _ = config_service.load_for_write(config, allow_create=True)
    for name, wl in cfg_write.workloads.items():
        wl.enabled = name in selected_names
        if wl.enabled and name in intensities:
            wl.intensity = intensities[name]
        cfg_write.workloads[name] = wl
    cfg_write.save(target)
    if set_default:
        config_service.write_saved_config_path(target)
    if stale:
        ui.present.warning(f"Saved default config not found: {stale}")
    ui.present.success(f"Workload selection saved to {target}")


def select_plugins_interactively(
    ui: UI,
    registry: PluginRegistry,
    enabled_map: Dict[str, bool]
) -> Optional[Set[str]]:
    """Prompt the user to enable/disable plugins using arrows and space."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        ui.present.error("Interactive selection requires a TTY.")
        return None
        
    headers, rows = build_plugin_table(registry, enabled=enabled_map)
    ui.tables.show(TableModel(title="Available Workload Plugins", columns=headers, rows=rows))
    
    items = []
    for name, plugin in registry.available().items():
        desc = getattr(plugin, "description", "") or ""
        items.append(PickItem(id=name, title=name, description=desc))
    
    selection = ui.picker.pick_many(items, title="Select Workload Plugins")
    
    if not selection:
        ui.present.warning("Selection cancelled.")
        return None
        
    return {s.id for s in selection}


def apply_plugin_selection(
    ui: UI,
    config_service: ConfigService,
    registry: PluginRegistry,
    selection: Set[str],
    config: Optional[Path],
    set_default: bool,
) -> Dict[str, bool]:
    """
    Persist the selected plugins to the config and return the updated enabled map.
    """
    cfg, target, stale, _ = config_service.load_for_write(config, allow_create=True)
    for name in registry.available():
        workload = cfg.workloads.get(name) or WorkloadConfig(plugin=name, options={})
        workload.enabled = name in selection
        cfg.workloads[name] = workload
    cfg.save(target)
    if set_default:
        config_service.write_saved_config_path(target)
    if stale:
        ui.present.warning(f"Saved default config not found: {stale}")
    ui.present.success(f"Plugin selection saved to {target}")
    return {
        name: cfg.workloads.get(name, WorkloadConfig(plugin=name)).enabled
        for name in registry.available()
    }
