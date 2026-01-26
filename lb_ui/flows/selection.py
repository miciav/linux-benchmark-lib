"""Workflows for interactive selection of plugins and workloads."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Set

from lb_app.api import (
    BenchmarkConfig,
    ConfigService,
    PluginRegistry,
    WorkloadConfig,
    build_plugin_table,
)
from lb_ui.tui.core.protocols import UI
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
    if not is_tty_available():
        raise UIFlowError("Interactive selection requires a TTY.")

    available_plugins = registry.available()
    items = []
    missing_plugins: set[str] = set()

    intensities_catalog = [
        PickItem(id="user_defined", title="user_defined", description="Custom intensity"),
        PickItem(id="low", title="low", description="Light load"),
        PickItem(id="medium", title="medium", description="Balanced load"),
        PickItem(id="high", title="high", description="Aggressive load"),
    ]

    # Prepare items for picker with variants as intensities
    configured_plugins = set()
    platform_cfg, _, _ = config_service.load_platform_config()

    for name, wl in sorted(cfg.workloads.items()):
        configured_plugins.add(wl.plugin)
        plugin_obj = available_plugins.get(wl.plugin)
        if plugin_obj is None:
            missing_plugins.add(wl.plugin)
        description = getattr(plugin_obj, "description", "") if plugin_obj else "missing plugin"
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
                    selected=variant.id == current_intensity,
                )
            )

        item = PickItem(
            id=name,
            title=name,
            description=f"Plugin: {wl.plugin} | Intensity: {current_intensity} | {description}",
            payload=wl,
            variants=variant_list,
            search_blob=f"{name} {wl.plugin} {description}",
            selected=True,
        )
        items.append(item)

    # Add unconfigured plugins as selectable or disabled items
    for plugin_name in sorted(available_plugins.keys()):
        if plugin_name in configured_plugins:
            continue

        plugin_obj = available_plugins[plugin_name]
        description = getattr(plugin_obj, "description", "")
        is_plugin_platform_enabled = platform_cfg.is_plugin_enabled(plugin_name)

        if is_plugin_platform_enabled:
            # Shown as selectable, but not currently in workloads.
            # No [red] tags, the UI will show this as a normal, selectable item.
            items.append(
                PickItem(
                    id=plugin_name,
                    title=plugin_name,
                    description=f"{description} (Available - click to add to config)",
                    disabled=False,
                    selected=False,
                )
            )
        else:
            # Only plugins explicitly disabled in platform.json appear as disabled (red).
            items.append(
                PickItem(
                    id=plugin_name,
                    title=plugin_name,
                    description=f"{description} (Disabled in platform configuration)",
                    disabled=True,
                    selected=False,
                )
            )

    if missing_plugins:
        missing_list = ", ".join(sorted(missing_plugins))
        ui.present.warning(
            f"Missing plugins: {missing_list}. "
            "Install them or remove the workloads from the config."
        )
    elif not items:
        ui.present.warning("No plugins installed.")

    selection = ui.picker.pick_many(items, title="Select Configured Workloads")
    if selection is None:
        return
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
        if not ui.form.confirm(
            "Do you want to proceed with NO workloads configured?",
            default=False,
        ):
            raise UIFlowError("Workload selection cancelled.")

    cfg_write, target, stale, _ = config_service.load_for_write(config, allow_create=True)
    
    # 1. Remove workloads that were deselected
    for name in list(cfg_write.workloads.keys()):
        if name not in selected_names:
            cfg_write.workloads.pop(name, None)

    # 2. Add or update selected workloads
    for name in selected_names:
        if name in cfg_write.workloads:
            wl = cfg_write.workloads[name]
            if name in intensities:
                wl.intensity = intensities[name]
        else:
            # New workload from an enabled plugin
            # Name matches plugin_name here for new ones
            wl = WorkloadConfig(
                plugin=name,
                options={},
                intensity=intensities.get(name, "medium"),
            )
            cfg_write.workloads[name] = wl
            
            # Ensure plugin settings are populated
            if name not in cfg_write.plugin_settings:
                plugin = registry.get(name)
                if hasattr(plugin, "config_cls"):
                    cfg_write.plugin_settings[name] = plugin.config_cls()

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
    if not is_tty_available():
        raise UIFlowError("Interactive selection requires a TTY.")
        
    headers, rows = build_plugin_table(registry, enabled=enabled_map)
    ui.tables.show(TableModel(title="Available Workload Plugins", columns=headers, rows=rows))
    
    items = []
    for name, plugin in registry.available().items():
        desc = getattr(plugin, "description", "") or ""
        items.append(
            PickItem(
                id=name,
                title=name,
                description=desc,
                selected=enabled_map.get(name, False),
            )
        )
    
    selection = ui.picker.pick_many(items, title="Select Workload Plugins")

    if selection is None:
        ui.present.info("Selection cancelled.")
        return None
    if not selection:
        ui.present.warning("Selection cancelled.")
        return None
        
    return {s.id for s in selection}


def apply_plugin_selection(
    ui: UI,
    config_service: ConfigService,
    registry: PluginRegistry,
    selection: Set[str],
) -> Dict[str, bool]:
    """
    Persist the selected plugins to the config and return the updated enabled map.
    """
    cfg, target = config_service.set_plugin_selection(selection, registry)
    ui.present.success(f"Plugin selection saved to {target}")
    return {name: cfg.is_plugin_enabled(name) for name in registry.available()}
from lb_ui.flows.errors import UIFlowError
from lb_ui.tui.core.capabilities import is_tty_available
