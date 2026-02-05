"""
Service for managing and configuring test scenarios, specifically for
Multipass integration.
"""

import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from lb_app.services.config_service import ConfigService
from lb_app.ui_interfaces import UIAdapter, NoOpUIAdapter


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

    def __init__(
        self,
        ui: UIAdapter | None = None,
        config_service: ConfigService | None = None,
    ) -> None:
        self.ui: UIAdapter = ui or NoOpUIAdapter()
        self.config_service: ConfigService = config_service or ConfigService()

    def get_multipass_intensity(
        self, force_env: Optional[str] = None
    ) -> Dict[str, Any]:
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
        self, force_interactive: bool = False, default_level: str = "medium"
    ) -> tuple[str, str]:
        """Select a Multipass scenario; fall back to defaults when non-interactive."""
        cfg = self.config_service.create_default_config()
        workload_names = list(cfg.workloads.keys())
        if not workload_names:
            return "stress_ng", default_level

        options = list(dict.fromkeys(workload_names + ["multi"]))

        interactive = force_interactive or (sys.stdin.isatty() and sys.stdout.isatty())
        if interactive:
            choice = self.ui.prompt_multipass_scenario(options, default_level)
            if choice is not None:
                return choice

        return options[0], default_level

    def build_multipass_scenario(
        self, intensity: Dict[str, Any], selection: str
    ) -> MultipassScenario:
        """Construct the scenario details for the test plan."""

        # Defaults for generic single workload
        target = "tests/e2e/test_multipass_benchmark.py"
        target_label = "benchmark"
        workload_label = selection
        duration_label = f"{selection} (default duration)"
        workload_rows = []
        env_vars = {"LB_MULTIPASS_WORKLOADS": selection}

        # Helper to build specific rows
        def row_stress_ng():
            return (
                "stress_ng",
                f"{intensity['stress']}s",
                "1",
                "0s/0s",
                f"timeout={intensity['stress']}s, cpu_workers=1",
            )

        def row_dd():
            return (
                "dd",
                f"approx {intensity['dd_count']}MiB",
                "1",
                "0s/0s",
                f"bs=1M, count={intensity['dd_count']}",
            )

        def row_fio():
            return (
                "fio",
                f"{intensity['fio_runtime']}s",
                "1",
                "0s/0s",
                f"size={intensity['fio_size']}, randrw, bs=4k",
            )

        if selection == "multi":
            target = "tests/e2e/test_multipass_multi_workloads.py"
            target_label = "multi-workloads"
            workload_label = "stress_ng, dd, fio"
            duration_label = (
                f"stress_ng {intensity['stress']}s; "
                f"dd ~{intensity['dd_count']}MiB; "
                f"fio {intensity['fio_runtime']}s/{intensity['fio_size']}"
            )
            workload_rows = [row_stress_ng(), row_dd(), row_fio()]
            env_vars = {}  # Uses its own hardcoded logic or we could migrate it

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
            # Generic fallback for workloads not explicitly detailed in intensity
            duration_label = "default"
            workload_rows = [(selection, "default", "1", "0s/0s", "default config")]

        return MultipassScenario(
            target=target,
            target_label=target_label,
            workload_label=workload_label,
            duration_label=duration_label,
            workload_rows=workload_rows,
            env_vars=env_vars,
        )
