"""
Service for performing environment health checks (doctor).
"""

import importlib
import platform
import shutil
from typing import List, Tuple, Optional

from lb_app.services.doctor_types import DoctorCheckGroup, DoctorCheckItem, DoctorReport
from lb_app.services.config_service import ConfigService
from lb_controller.api import (
    BenchmarkConfig,
    ConnectivityService,
)
from lb_plugins.api import create_registry


class DoctorService:
    """Service to check local prerequisites and environment health."""

    def __init__(
        self,
        config_service: Optional[ConfigService] = None,
    ):
        self.config_service = config_service or ConfigService()

    def _check_import(self, name: str) -> bool:
        try:
            importlib.import_module(name)
            return True
        except Exception:
            return False

    def _check_command(self, name: str) -> bool:
        return shutil.which(name) is not None

    def _build_check_group(
        self, title: str, items: List[Tuple[str, bool, bool]]
    ) -> DoctorCheckGroup:
        failures = 0
        check_items = []
        for label, ok, required in items:
            check_items.append(DoctorCheckItem(label, ok, required))
            failures += 0 if ok or not required else 1
        return DoctorCheckGroup(title, check_items, failures)

    def check_controller(self) -> DoctorReport:
        """Check controller-side requirements (Python deps, ansible-runner)."""
        groups = []
        py_deps = [
            ("psutil", self._check_import("psutil"), True),
            ("pandas", self._check_import("pandas"), True),
            ("numpy", self._check_import("numpy"), True),
            ("matplotlib", self._check_import("matplotlib"), True),
            ("seaborn", self._check_import("seaborn"), True),
            ("jc", self._check_import("jc"), True),
            (
                "influxdb-client (optional)",
                self._check_import("influxdb_client"),
                False,
            ),
        ]
        groups.append(self._build_check_group("Python Dependencies", py_deps))

        controller_tools = [
            ("ansible-runner (python)", self._check_import("ansible_runner"), True),
            ("ansible-playbook", self._check_command("ansible-playbook"), True),
        ]
        groups.append(self._build_check_group("Controller Tools", controller_tools))

        resolved, stale = self.config_service.resolve_config_path(None)
        cfg_items = [
            ("Active config", resolved is not None, False),
            ("Stale default path", stale is None, False),
        ]
        groups.append(self._build_check_group("Config Resolution", cfg_items))

        info = (
            f"Python: {platform.python_version()} ({platform.python_implementation()}) "
            f"on {platform.system()} {platform.release()}"
        )

        return DoctorReport(
            groups=groups,
            info_messages=[info],
            total_failures=sum(g.failures for g in groups),
        )

    def check_local_tools(self) -> DoctorReport:
        """Check local workload tools required by installed plugins."""
        registry = create_registry()
        items: List[Tuple[str, bool, bool]] = []

        # Common system tools that are always good to have
        common_tools = ["sar", "vmstat", "iostat", "mpstat", "pidstat"]
        for tool in common_tools:
            items.append(
                (f"{tool} (system)", self._check_command(tool), False)
            )

        # Plugin-specific tools
        for plugin in registry.available(load_entrypoints=True).values():
            # Support both Legacy and new Interface via duck typing or method presence
            if hasattr(plugin, "get_required_local_tools"):
                required_tools = plugin.get_required_local_tools()
                for tool in required_tools:
                    label = f"{tool} ({plugin.name})"
                    items.append((label, self._check_command(tool), True))

        messages = []
        if not items:
            messages.append("No plugins with local tool requirements found.")
            return DoctorReport(groups=[], info_messages=messages, total_failures=0)

        # Sort by label
        items.sort(key=lambda x: x[0])
        group = self._build_check_group("Local Workload Tools", items)
        return DoctorReport(
            groups=[group],
            info_messages=messages,
            total_failures=group.failures,
        )

    def check_multipass(self) -> DoctorReport:
        """Check if Multipass is installed (used by integration test)."""
        items = [("multipass", self._check_command("multipass"), True)]
        group = self._build_check_group("Multipass", items)
        return DoctorReport(
            groups=[group], info_messages=[], total_failures=group.failures
        )

    def check_remote_hosts(
        self,
        config: Optional[BenchmarkConfig] = None,
        timeout_seconds: int = 10,
    ) -> DoctorReport:
        """Check SSH connectivity to configured remote hosts.

        Args:
            config: Benchmark configuration with remote hosts.
                If None, loads from default config path.
            timeout_seconds: Timeout for each host connection check.

        Returns:
            DoctorReport with connectivity results for each host.
        """
        # Load config if not provided
        if config is None:
            cfg, _, _ = self.config_service.load_for_read(None)
        else:
            cfg = config

        # Check if remote hosts are configured
        if not cfg.remote_hosts:
            return DoctorReport(
                groups=[],
                info_messages=["No remote hosts configured."],
                total_failures=0,
            )

        # Check connectivity using the controller service
        connectivity_service = ConnectivityService(timeout_seconds=timeout_seconds)
        report = connectivity_service.check_hosts(cfg.remote_hosts, timeout_seconds)

        # Convert to DoctorReport format
        items: List[Tuple[str, bool, bool]] = []
        for result in report.results:
            label = f"{result.name} ({result.address})"
            if result.reachable and result.latency_ms is not None:
                label += f" - {result.latency_ms:.0f}ms"
            elif not result.reachable and result.error_message:
                label += f" - {result.error_message}"
            items.append((label, result.reachable, True))

        group = self._build_check_group("Remote Host Connectivity", items)

        info_messages = [
            f"Checked {report.total_count} host(s) with {timeout_seconds}s timeout"
        ]
        if report.all_reachable:
            info_messages.append("All hosts are reachable.")
        else:
            info_messages.append(
                f"Unreachable hosts: {', '.join(report.unreachable_hosts)}"
            )

        return DoctorReport(
            groups=[group],
            info_messages=info_messages,
            total_failures=group.failures,
        )

    def check_all(self) -> DoctorReport:
        """Run all checks."""
        r1 = self.check_controller()
        r2 = self.check_local_tools()
        r3 = self.check_multipass()

        return DoctorReport(
            groups=r1.groups + r2.groups + r3.groups,
            info_messages=r1.info_messages + r2.info_messages + r3.info_messages,
            total_failures=r1.total_failures + r2.total_failures + r3.total_failures,
        )
