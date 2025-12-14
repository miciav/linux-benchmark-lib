"""
Service for performing environment health checks (doctor).
"""

import importlib
import platform
import shutil
from typing import List, Tuple, Optional

from .config_service import ConfigService
from .plugin_service import create_registry
from lb_controller.ui_interfaces import UIAdapter, NoOpUIAdapter

"""
Service for performing environment health checks (doctor).
"""

import importlib
import platform
import shutil
from typing import List, Tuple, Optional

from .config_service import ConfigService
from .plugin_service import create_registry
from .doctor_types import DoctorReport, DoctorCheckGroup, DoctorCheckItem

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

    def _build_check_group(self, title: str, items: List[Tuple[str, bool, bool]]) -> DoctorCheckGroup:
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
            ("influxdb-client (optional)", self._check_import("influxdb_client"), False),
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

        info = f"Python: {platform.python_version()} ({platform.python_implementation()}) on {platform.system()} {platform.release()}"
        
        return DoctorReport(
            groups=groups, 
            info_messages=[info], 
            total_failures=sum(g.failures for g in groups)
        )

    def check_local_tools(self) -> DoctorReport:
        """Check local workload tools required by installed plugins."""
        registry = create_registry()
        items: List[Tuple[str, bool, bool]] = []
        
        # Common system tools that are always good to have
        common_tools = ["sar", "vmstat", "iostat", "mpstat", "pidstat"]
        for tool in common_tools:
            items.append((f"{tool} (system)", self._check_command(tool), False)) # Not strictly required but recommended

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
        return DoctorReport(groups=[group], info_messages=messages, total_failures=group.failures)

    def check_multipass(self) -> DoctorReport:
        """Check if Multipass is installed (used by integration test)."""
        items = [("multipass", self._check_command("multipass"), True)]
        group = self._build_check_group("Multipass", items)
        return DoctorReport(groups=[group], info_messages=[], total_failures=group.failures)

    def check_all(self) -> DoctorReport:
        """Run all checks."""
        r1 = self.check_controller()
        r2 = self.check_local_tools()
        r3 = self.check_multipass()
        
        return DoctorReport(
            groups=r1.groups + r2.groups + r3.groups,
            info_messages=r1.info_messages + r2.info_messages + r3.info_messages,
            total_failures=r1.total_failures + r2.total_failures + r3.total_failures
        )

