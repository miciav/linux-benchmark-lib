"""System info summarization for run outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, IO

from lb_controller.api import RunJournal
from lb_app.ui_interfaces import DashboardHandle, UIAdapter


def attach_system_info(
    journal: RunJournal,
    base_dir: Path,
    hosts: list[str],
    dashboard: DashboardHandle | None,
    ui_adapter: UIAdapter | None,
    log_file: IO[str] | None = None,
) -> bool:
    """Load system info summaries and surface them in metadata/logs."""
    summaries = collect_system_info(hosts, base_dir, journal)
    if not summaries:
        return False
    log_system_info(summaries, dashboard, ui_adapter, log_file)
    return True


def collect_system_info(
    hosts: list[str],
    base_dir: Path,
    journal: RunJournal,
) -> dict[str, str]:
    """Gather system info summaries for each host and update journal metadata."""
    summaries: dict[str, str] = {}
    for host in hosts:
        summary = find_system_summary(base_dir, host)
        if summary:
            summaries[host] = summary
            journal.metadata.setdefault("system_info", {})[host] = summary
    return summaries


def find_system_summary(base_dir: Path, host: str) -> str | None:
    """Return the first available system info summary for a host."""
    for candidate in system_info_candidates(base_dir, host):
        if candidate.exists():
            summary = summarize_system_info(candidate)
            if summary:
                return summary
    return None


def system_info_candidates(base_dir: Path, host: str) -> list[Path]:
    """Return candidate paths for system info files for a given host."""
    return [
        base_dir / host / "system_info.json",
        base_dir / "system_info.json",
    ]


def summarize_system_info(path: Path) -> str | None:
    """Return a one-line summary for a system_info.json file."""
    data = load_json(path)
    if not isinstance(data, dict):
        return None
    os_part = format_os_summary(data)
    cpu_part = format_cpu_summary(data)
    mem_part = format_memory_summary(data)
    disk_part = format_disk_summary(data)
    parts = [os_part, cpu_part, mem_part, disk_part]
    parts = [part for part in parts if part]
    return " | ".join(parts) if parts else None


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def format_os_summary(data: dict[str, Any]) -> str:
    os_info = data.get("os", {}) if isinstance(data, dict) else {}
    kernel = data.get("kernel", {}) if isinstance(data, dict) else {}
    os_name = os_info.get("name") or os_info.get("id") or "Unknown OS"
    os_ver = os_info.get("version") or os_info.get("version_id") or ""
    kernel_rel = kernel.get("release") or kernel.get("version") or "kernel ?"
    return f"OS: {os_name} {os_ver}".strip() + f" | Kernel: {kernel_rel}"


def format_cpu_summary(data: dict[str, Any]) -> str:
    cpu = data.get("cpu", {}) if isinstance(data, dict) else {}
    model = (
        cpu.get("model_name")
        or cpu.get("model")
        or cpu.get("model_name:")
        or cpu.get("modelname")
        or cpu.get("architecture")
    )
    phys = cpu.get("physical_cpus") or cpu.get("cpu_cores") or "?"
    logi = cpu.get("logical_cpus") or cpu.get("cpus") or "?"
    return f"CPU: {model or '?'} ({phys}c/{logi}t)"


def format_memory_summary(data: dict[str, Any]) -> str:
    mem = data.get("memory", {}) if isinstance(data, dict) else {}
    ram_total = mem.get("total_bytes") or mem.get("memtotal") or mem.get("memtotal:")
    ram_str = to_gib(ram_total) if ram_total is not None else "?"
    return f"RAM: {ram_str}"


def format_disk_summary(data: dict[str, Any]) -> str | None:
    disks = data.get("disks", []) if isinstance(data, dict) else []
    if not isinstance(disks, list) or not disks:
        return None
    first = disks[0]
    if not isinstance(first, dict):
        return None
    name = first.get("name") or "disk"
    size = first.get("size_bytes") or first.get("size") or ""
    rota = first.get("rotational")
    kind = "SSD" if rota is False else "HDD" if rota is True else "disk"
    size_str = to_gib(size) if size else ""
    disk_summary = f"{name} {kind} {size_str}".strip()
    return f"Disk: {disk_summary}" if disk_summary else None


def to_gib(val: Any) -> str:
    try:
        return f"{int(val) / (1024**3):.1f}G"
    except Exception:
        return "?"


def log_system_info(
    summaries: dict[str, str],
    dashboard: DashboardHandle | None,
    ui_adapter: UIAdapter | None,
    log_file: IO[str] | None,
) -> None:
    """Emit system info summaries to available sinks."""
    for host, summary in summaries.items():
        line = f"{host}: {summary}"
        if dashboard:
            dashboard.add_log(f"[system] System info: {line}")
            dashboard.mark_event("system_info")
            dashboard.refresh()
        elif ui_adapter:
            ui_adapter.show_info(f"[system] {line}")
        else:
            print(f"[system] {line}")
        if log_file:
            try:
                log_file.write(f"[system] System info: {line}\n")
                log_file.flush()
            except Exception:
                pass
