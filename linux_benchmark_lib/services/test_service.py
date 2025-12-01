"""
Service for managing and configuring test scenarios, specifically for Multipass integration.
"""

import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..benchmark_config import BenchmarkConfig
from .config_service import ConfigService
from ..ui import get_ui_adapter
from ..ui.tui_prompts import prompt_multipass
from ..ui.types import UIAdapter


@dataclass
class MultipassScenario:
    """Configuration for a Multipass test run."""
    target: str
    target_label: str
    workload_label: str
    duration_label: str
    workload_rows: List[Tuple[str, str, str, str, str]]
    env_vars: Dict[str, str]


class TestService:
    """Service for test configuration and interactions."""

    __test__ = False  # Prevent pytest from collecting this production service as a test

    def __init__(self, ui_adapter: Optional[UIAdapter] = None):
        self.ui = ui_adapter or get_ui_adapter()

    def get_multipass_intensity(self, force_env: Optional[str] = None) -> Dict[str, Any]:
        """
        Return intensity parameters based on LB_MULTIPASS_FORCE env var or argument.
        """
        level = (force_env or os.environ.get("LB_MULTIPASS_FORCE", "medium")).lower()
        normalized = {
            "bassa": "low",
            "low": "low",
            "media": "medium",
            "medium": "medium",
            "alta": "high",
            "high": "high",
        }.get(level, "medium")

        if normalized == "low":
            return {
                "level": "low",
                "stress": 3,
                "dd_count": 8,
                "fio_runtime": 3,
                "fio_size": "32M",
                "stress_duration": 3,
                "stress_timeout": 3,
            }
        if normalized == "high":
            return {
                "level": "high",
                "stress": 10,
                "dd_count": 64,
                "fio_runtime": 10,
                "fio_size": "128M",
                "stress_duration": 10,
                "stress_timeout": 10,
            }
        return {
            "level": "medium",
            "stress": 5,
            "dd_count": 32,
            "fio_runtime": 5,
            "fio_size": "64M",
            "stress_duration": 5,
            "stress_timeout": 5,
        }

    def select_multipass(
        self, multi_workloads: bool, default_level: str = "medium"
    ) -> Tuple[str, str]:
        """
        Return (scenario, intensity_level) using the Textual prompt when possible.
        """
        if multi_workloads:
            return "multi", default_level

        cfg_preview = ConfigService().create_default_config().workloads
        names = sorted(cfg_preview.keys())
        options = list(dict.fromkeys(names + ["multi"]).keys())

        if sys.stdin.isatty():
            result = prompt_multipass(options, default_level=default_level)
            if result:
                scenario, level = result
                self.ui.show_success(f"Selected: {scenario} @ {level}")
                return scenario, level

        # Fallback for non-interactive contexts
        self.ui.show_info(f"Non-interactive mode, defaulting to stress_ng ({default_level}).")
        return "stress_ng", default_level

    def build_multipass_scenario(
        self, intensity: Dict[str, Any], selection: str
    ) -> MultipassScenario:
        """Construct the scenario details for the test plan."""
        
        # Defaults for generic single workload
        target = "tests/integration/test_multipass_benchmark.py"
        target_label = "benchmark"
        workload_label = selection
        duration_label = f"{selection} (default duration)"
        workload_rows = []
        env_vars = {"LB_MULTIPASS_WORKLOADS": selection}

        # Helper to build specific rows
        def row_stress_ng():
            return ("stress_ng", f"{intensity['stress']}s", "1", "0s/0s", f"timeout={intensity['stress']}s, cpu_workers=1")
        
        def row_dd():
            return ("dd", f"approx {intensity['dd_count']}MiB", "1", "0s/0s", f"bs=1M, count={intensity['dd_count']}")

        def row_fio():
            return ("fio", f"{intensity['fio_runtime']}s", "1", "0s/0s", f"size={intensity['fio_size']}, randrw, bs=4k")

        if selection == "multi":
            target = "tests/integration/test_multipass_multi_workloads.py"
            target_label = "multi-workloads"
            workload_label = "stress_ng, dd, fio"
            duration_label = (
                f"stress_ng {intensity['stress']}s; "
                f"dd ~{intensity['dd_count']}MiB; "
                f"fio {intensity['fio_runtime']}s/{intensity['fio_size']}"
            )
            workload_rows = [row_stress_ng(), row_dd(), row_fio()]
            env_vars = {} # Uses its own hardcoded logic or we could migrate it
            
        elif selection == "stress_ng":
            duration_label = f"stress_ng {intensity['stress']}s"
            workload_rows = [row_stress_ng()]
            
        elif selection == "dd":
            duration_label = f"dd ~{intensity['dd_count']}MiB"
            workload_rows = [row_dd()]
            
        elif selection == "fio":
            duration_label = f"fio {intensity['fio_runtime']}s"
            workload_rows = [row_fio()]
            
        else:
            # Generic fallback for iperf3 or others not explicitly detailed in intensity
            duration_label = "default"
            workload_rows = [(selection, "default", "1", "0s/0s", "default config")]

        return MultipassScenario(
            target=target,
            target_label=target_label,
            workload_label=workload_label,
            duration_label=duration_label,
            workload_rows=workload_rows,
            env_vars=env_vars
        )
