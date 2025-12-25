from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List

import typer

from lb_app.api import TestService, DoctorService
from lb_controller.api import ConfigService
from lb_ui.tui.system.models import PickItem


def create_test_app(test_service: TestService, doctor_service: DoctorService, ui) -> typer.Typer:
    """Build the test Typer app for integration helpers."""
    app = typer.Typer(help="Convenience helpers to run integration tests.", no_args_is_help=True)

    @app.command(
        "multipass",
        context_settings={
            "allow_extra_args": True,
            "ignore_unknown_options": True,
        },
    )
    def test_multipass(
        ctx: typer.Context,
        output: Path = typer.Option(
            Path("tests/results"),
            "--output",
            "-o",
            help="Directory to store test artifacts.",
        ),
        vm_count: int = typer.Option(
            1,
            "--vm-count",
            help="Number of Multipass VMs to launch.",
        ),
        multi_workloads: bool = typer.Option(
            False,
            "--multi-workloads",
            help="Run the multi-workload Multipass scenario.",
        ),
    ) -> None:
        """Run the Multipass integration test helper."""
        if not doctor_service._check_command("multipass"):
            ui.present.error("multipass not found in PATH.")
            raise typer.Exit(1)
        if not doctor_service._check_import("pytest"):
            ui.present.error("pytest is not installed.")
            raise typer.Exit(1)

        output = output.expanduser()
        output.mkdir(parents=True, exist_ok=True)

        default_level = "medium"
        scenario_choice = "stress_ng"
        level = default_level

        if multi_workloads:
            scenario_choice = "multi"
        else:
            cfg_preview = ConfigService().create_default_config().workloads
            names = sorted(cfg_preview.keys())
            options = list(dict.fromkeys(names + ["multi"]).keys())

            items = []
            for opt in options:
                variants = [PickItem(id=f"{opt}:{l}", title=l) for l in ["low", "medium", "high"]]
                items.append(PickItem(id=opt, title=opt, variants=variants, description=f"Run {opt} scenario"))

            selection = ui.picker.pick_one(items, title="Select Multipass Scenario & Intensity")
            if selection:
                if ":" in selection.id:
                    scenario_choice, level = selection.id.split(":")
                else:
                    scenario_choice = selection.id
                    level = default_level
                ui.present.success(f"Selected: {scenario_choice} @ {level}")
            else:
                ui.present.info(f"Using default: {scenario_choice} @ {level}")

        intensity = test_service.get_multipass_intensity()
        scenario = test_service.build_multipass_scenario(intensity, scenario_choice)

        env = os.environ.copy()
        env["LB_TEST_RESULTS_DIR"] = str(output)
        env["LB_MULTIPASS_VM_COUNT"] = str(vm_count)
        env["LB_MULTIPASS_FORCE"] = level
        for key, value in scenario.env_vars.items():
            env[key] = value

        extra_args = list(ctx.args) if ctx.args else []
        cmd: List[str] = [sys.executable, "-m", "pytest", scenario.target]
        if extra_args:
            cmd.extend(extra_args)

        label = "multi-VM" if vm_count > 1 else "single-VM"
        ui.present.info(f"VM count: {vm_count} ({label})")
        ui.present.info(f"Scenario: {scenario.workload_label} -> {scenario.target_label}")
        ui.present.info(f"Artifacts: {output}")

        try:
            result = subprocess.run(cmd, check=False, env=env)
        except Exception as exc:
            ui.present.error(f"Failed to launch Multipass test: {exc}")
            raise typer.Exit(1)

        if result.returncode != 0:
            ui.present.error(f"`pytest` exited with {result.returncode}")
            raise typer.Exit(result.returncode)

    return app
