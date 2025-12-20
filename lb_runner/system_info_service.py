"""System info collection service wrapper."""

from __future__ import annotations

from lb_runner.system_info import SystemInfo, collect_system_info


class SystemInfoCollector:
    """Collect system information using the core helpers."""

    def collect(self) -> SystemInfo:
        return collect_system_info()
