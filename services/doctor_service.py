"""
Service for performing environment health checks (doctor).
"""

import importlib
import platform
import shutil
from typing import List, Tuple, Optional

from services.config_service import ConfigService
from services.plugin_service import create_registry
from ui import get_ui_adapter
from ui.types import UIAdapter

class DoctorService:
    """Service to check local prerequisites and environment health."""

    def __init__(
        self,
        ui_adapter: Optional[UIAdapter] = None,
        config_service: Optional[ConfigService] = None,
    ):
        self.ui = ui_adapter or get_ui_adapter()
        self.config_service = config_service or ConfigService()

    def _check_import(self, name: str) -> bool:
        try:
            importlib.import_module(name)
            return True
        except Exception:
            return False

    def _check_command(self, name: str) -> bool:
        return shutil.which(name) is not None

    def _render_check_table(self, title: str, items: List[Tuple[str, bool, bool]]) -> int:
        failures = 0
        rows = []
        for label, ok, required in items:
            rows.append([label, "✓" if ok else "✗"])
            failures += 0 if ok or not required else 1
        self.ui.show_table(title, ["Item", "Status"], rows)
        return failures

    def check_controller(self) -> int:
        """Check controller-side requirements (Python deps, ansible-runner)."""
        failures = 0
        py_deps = [
            ("psutil", self._check_import("psutil"), True),
            ("pandas", self._check_import("pandas"), True),
            ("numpy", self._check_import("numpy"), True),
            ("matplotlib", self._check_import("matplotlib"), True),
            ("seaborn", self._check_import("seaborn"), True),
            ("iperf3 (python)", self._check_import("iperf3"), True),
            ("jc", self._check_import("jc"), True),
            ("influxdb-client (optional)", self._check_import("influxdb_client"), False),
        ]
        failures += self._render_check_table("Python Dependencies", py_deps)

        controller_tools = [
            ("ansible-runner (python)", self._check_import("ansible_runner"), True),
            ("ansible-playbook", self._check_command("ansible-playbook"), True),
        ]
        failures += self._render_check_table("Controller Tools", controller_tools)

        resolved, stale = self.config_service.resolve_config_path(None)
        cfg_items = [
            ("Active config", resolved is not None, False),
            ("Stale default path", stale is None, False),
        ]
        failures += self._render_check_table("Config Resolution", cfg_items)

        self.ui.show_info(
            f"Python: {platform.python_version()} ({platform.python_implementation()}) on {platform.system()} {platform.release()}"
        )
        return failures

    def check_local_tools(self) -> int:
        """Check local workload tools required by installed plugins."""
        registry = create_registry()
        items: List[Tuple[str, bool, bool]] = []
        
        # Common system tools that are always good to have
        common_tools = ["sar", "vmstat", "iostat", "mpstat", "pidstat"]
        for tool in common_tools:
            items.append((f"{tool} (system)", self._check_command(tool), False)) # Not strictly required but recommended

        # Plugin-specific tools
        for plugin in registry.available().values():
            # Support both Legacy and new Interface via duck typing or method presence
            if hasattr(plugin, "get_required_local_tools"):
                required_tools = plugin.get_required_local_tools()
                for tool in required_tools:
                    label = f"{tool} ({plugin.name})"
                    items.append((label, self._check_command(tool), True))

        if not items:
             self.ui.show_info("No plugins with local tool requirements found.")
             return 0

        # Sort by label
        items.sort(key=lambda x: x[0])
        return self._render_check_table("Local Workload Tools", items)

    def check_multipass(self) -> int:
        """Check if Multipass is installed (used by integration test)."""
        items = [("multipass", self._check_command("multipass"), True)]
        return self._render_check_table("Multipass", items)

    def check_all(self) -> int:
        """Run all checks."""
        failures = 0
        failures += self.check_controller()
        failures += self.check_local_tools()
        failures += self.check_multipass()
        return failures
