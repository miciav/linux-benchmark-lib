"""Run plan helpers for UI display."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from lb_controller.api import BenchmarkConfig, PlatformConfig
from lb_plugins.api import PluginRegistry, WorkloadIntensity


def build_run_plan(
    cfg: BenchmarkConfig,
    tests: list[str],
    *,
    execution_mode: str = "remote",
    registry: PluginRegistry,
    platform_config: PlatformConfig | None = None,
) -> list[dict[str, Any]]:
    """Build a detailed plan for the workloads to be run."""
    mode = (execution_mode or "remote").lower()
    return [
        build_plan_item(cfg, name, mode, registry, platform_config) for name in tests
    ]


def build_plan_item(
    cfg: BenchmarkConfig,
    name: str,
    mode: str,
    registry: PluginRegistry,
    platform_config: PlatformConfig | None = None,
) -> dict[str, Any]:
    """Assemble a single plan item for display."""
    workload = cfg.workloads.get(name)
    item = _build_plan_item_base(cfg, name, workload)
    if workload is None:
        return item

    if _mark_platform_disabled(item, workload, name, platform_config):
        return item

    plugin = safe_get_plugin(registry, workload.plugin)
    if plugin is None:
        item["status"] = "[red]✗ (Missing)[/red]"
        return item

    _apply_plan_details(item, workload, plugin)

    item["status"] = status_for_mode(mode, default=item["status"])
    return item


def safe_get_plugin(registry: PluginRegistry, plugin_name: str):
    """Return plugin from registry or None on error."""
    try:
        return registry.get(plugin_name)
    except Exception:
        return None


def resolve_workload_config(
    workload: Any,
    plugin: Any,
) -> tuple[Any | None, str | None]:
    """Resolve config object from intensity presets or user options."""
    try:
        config_obj = _resolve_preset_config(workload, plugin)
        if config_obj is None:
            config_obj = _resolve_user_config(workload, plugin)
        return config_obj, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def format_plan_details(config_obj: Any | None) -> str:
    """Return a concise description for a workload config."""
    if not config_obj:
        return "-"
    data = config_to_dict(config_obj)
    if not data:
        return str(config_obj)
    parts = summarize_config_fields(data)
    if not parts:
        return "-"
    return ", ".join(parts)


def config_to_dict(config_obj: Any) -> dict[str, Any]:
    """Convert config object to a dictionary when possible."""
    if isinstance(config_obj, dict):
        return config_obj
    try:
        from pydantic import BaseModel

        if isinstance(config_obj, BaseModel):
            return config_obj.model_dump()
    except Exception:
        pass
    try:
        if is_dataclass(config_obj):
            return asdict(config_obj)
    except Exception:
        pass
    return {}


def summarize_config_fields(data: dict[str, Any]) -> list[str]:
    """Format key config fields into a short, human-friendly list."""
    parts: list[str] = []
    _append_duration_field(parts, data)
    _append_named_fields(parts, data)
    if len(parts) < 2:
        return _fallback_config_parts(data)
    return parts


def status_for_mode(mode: str, default: str = "[yellow]?[/yellow]") -> str:
    """Return a status tag based on execution mode."""
    mapping = {
        "docker": "[green]Docker (Ansible)[/green]",
        "multipass": "[green]Multipass[/green]",
        "remote": "[blue]Remote[/blue]",
    }
    return mapping.get(mode, default)


def _build_plan_item_base(
    cfg: BenchmarkConfig, name: str, workload: Any | None
) -> dict[str, Any]:
    return {
        "name": name,
        "plugin": workload.plugin if workload else "unknown",
        "status": "[yellow]?[/yellow]",
        "intensity": workload.intensity if workload else "-",
        "details": "-",
        "repetitions": str(cfg.repetitions),
    }


def _mark_platform_disabled(
    item: dict[str, Any],
    workload: Any,
    name: str,
    platform_config: PlatformConfig | None,
) -> bool:
    if platform_config is None:
        return False
    plugin_name = workload.plugin or name
    if platform_config.is_plugin_enabled(plugin_name):
        return False
    item["status"] = "[yellow]skipped (disabled by platform)[/yellow]"
    return True


def _apply_plan_details(item: dict[str, Any], workload: Any, plugin: Any) -> None:
    config_obj, config_error = resolve_workload_config(workload, plugin)
    if config_error:
        item["details"] = f"[red]Config Error: {config_error}[/red]"
    else:
        item["details"] = format_plan_details(config_obj)


def _resolve_preset_config(workload: Any, plugin: Any) -> Any | None:
    if not workload.intensity or workload.intensity == "user_defined":
        return None
    try:
        level = WorkloadIntensity(workload.intensity)
    except ValueError:
        return None
    return plugin.get_preset_config(level)


def _resolve_user_config(workload: Any, plugin: Any) -> Any:
    if isinstance(workload.options, dict):
        return plugin.config_cls(**workload.options)
    return workload.options


def _append_duration_field(parts: list[str], data: dict[str, Any]) -> None:
    duration = data.get("timeout") or data.get("time") or data.get("runtime")
    if duration:
        parts.append(f"Time: {duration}s")


def _append_named_fields(parts: list[str], data: dict[str, Any]) -> None:
    _append_field_if_value(parts, data, "cpu_workers", "CPU")
    _append_field_if_present(parts, data, "vm_bytes", "VM")
    _append_field_if_present(parts, data, "bs", "BS")
    _append_field_if_value(parts, data, "count", "Count")
    _append_field_if_present(parts, data, "parallel", "Streams")
    _append_field_if_present(parts, data, "rw", "Mode")
    _append_field_if_present(parts, data, "iodepth", "Depth")


def _append_field_if_value(
    parts: list[str], data: dict[str, Any], key: str, label: str
) -> None:
    value = data.get(key)
    if value:
        parts.append(f"{label}: {value}")


def _append_field_if_present(
    parts: list[str], data: dict[str, Any], key: str, label: str
) -> None:
    if key in data:
        parts.append(f"{label}: {data[key]}")


def _fallback_config_parts(data: dict[str, Any]) -> list[str]:
    return [
        f"{key}={val}"
        for key, val in data.items()
        if val is not None and key not in ["extra_args"]
    ]
