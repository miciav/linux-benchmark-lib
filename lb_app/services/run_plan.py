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
        build_plan_item(cfg, name, mode, registry, platform_config)
        for name in tests
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
    item = {
        "name": name,
        "plugin": workload.plugin if workload else "unknown",
        "status": "[yellow]?[/yellow]",
        "intensity": workload.intensity if workload else "-",
        "details": "-",
        "repetitions": str(cfg.repetitions),
    }
    if workload is None:
        return item

    if platform_config is not None:
        plugin_name = workload.plugin or name
        if not platform_config.is_plugin_enabled(plugin_name):
            item["status"] = "[yellow]skipped (disabled by platform)[/yellow]"
            return item

    plugin = safe_get_plugin(registry, workload.plugin)
    if plugin is None:
        item["status"] = "[red]✗ (Missing)[/red]"
        return item

    config_obj, config_error = resolve_workload_config(workload, plugin)
    if config_error:
        item["details"] = f"[red]Config Error: {config_error}[/red]"
    else:
        item["details"] = format_plan_details(config_obj)

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
        config_obj = None
        if workload.intensity and workload.intensity != "user_defined":
            try:
                level = WorkloadIntensity(workload.intensity)
                config_obj = plugin.get_preset_config(level)
            except ValueError:
                pass
        if config_obj is None:
            if isinstance(workload.options, dict):
                config_obj = plugin.config_cls(**workload.options)
            else:
                config_obj = workload.options
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
    duration = data.get("timeout") or data.get("time") or data.get("runtime")
    if duration:
        parts.append(f"Time: {duration}s")

    if data.get("cpu_workers"):
        parts.append(f"CPU: {data['cpu_workers']}")
    if "vm_bytes" in data:
        parts.append(f"VM: {data['vm_bytes']}")
    if "bs" in data:
        parts.append(f"BS: {data['bs']}")
    if data.get("count"):
        parts.append(f"Count: {data['count']}")
    if "parallel" in data:
        parts.append(f"Streams: {data['parallel']}")
    if "rw" in data:
        parts.append(f"Mode: {data['rw']}")
    if "iodepth" in data:
        parts.append(f"Depth: {data['iodepth']}")

    if len(parts) < 2:
        parts = [
            f"{key}={val}"
            for key, val in data.items()
            if val is not None and key not in ["extra_args"]
        ]
    return parts


def status_for_mode(mode: str, default: str = "[yellow]?[/yellow]") -> str:
    """Return a status tag based on execution mode."""
    mapping = {
        "docker": "[green]Docker (Ansible)[/green]",
        "multipass": "[green]Multipass[/green]",
        "remote": "[blue]Remote[/blue]",
    }
    return mapping.get(mode, default)
