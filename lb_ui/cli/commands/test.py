from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List

import typer

from lb_ui.wiring.dependencies import UIContext
from lb_ui.tui.system.models import PickItem
from lb_plugins.api import create_registry


def create_test_app(ctx: UIContext) -> typer.Typer:
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
        typer_ctx: typer.Context,
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
        if not ctx.doctor_service._check_command("multipass"):
            ctx.ui.present.error("multipass not found in PATH.")
            raise typer.Exit(1)
        if not ctx.doctor_service._check_import("pytest"):
            ctx.ui.present.error("pytest is not installed.")
            raise typer.Exit(1)

        output = output.expanduser()
        output.mkdir(parents=True, exist_ok=True)

        default_level = "medium"
        scenario_choice = "stress_ng"
        level = default_level

        if multi_workloads:
            scenario_choice = "multi"
        else:
            registry = create_registry()
            names = sorted(registry.available().keys())
            options = list(dict.fromkeys(names + ["multi"]).keys())

            items = []
            for opt in options:
                variants = [
                    PickItem(id=f"{opt}:{level_name}", title=level_name)
                    for level_name in ["low", "medium", "high"]
                ]
                items.append(PickItem(id=opt, title=opt, variants=variants, description=f"Run {opt} scenario"))

            selection = ctx.ui.picker.pick_one(items, title="Select Multipass Scenario & Intensity")
            if selection:
                if ":" in selection.id:
                    scenario_choice, level = selection.id.split(":")
                else:
                    scenario_choice = selection.id
                    level = default_level
                ctx.ui.present.success(f"Selected: {scenario_choice} @ {level}")
            else:
                ctx.ui.present.info(f"Using default: {scenario_choice} @ {level}")

        intensity = ctx.test_service.get_multipass_intensity()
        scenario = ctx.test_service.build_multipass_scenario(intensity, scenario_choice)

        env = os.environ.copy()
        env["LB_TEST_RESULTS_DIR"] = str(output)
        env["LB_MULTIPASS_VM_COUNT"] = str(vm_count)
        env["LB_MULTIPASS_FORCE"] = level
        for key, value in scenario.env_vars.items():
            env[key] = value

        extra_args = list(typer_ctx.args) if typer_ctx.args else []
        cmd: List[str] = [sys.executable, "-m", "pytest", scenario.target]
        if extra_args:
            cmd.extend(extra_args)

        label = "multi-VM" if vm_count > 1 else "single-VM"
        ctx.ui.present.info(f"VM count: {vm_count} ({label})")
        ctx.ui.present.info(f"Scenario: {scenario.workload_label} -> {scenario.target_label}")
        ctx.ui.present.info(f"Artifacts: {output}")

        try:
            result = subprocess.run(cmd, check=False, env=env)
        except Exception as exc:
            ctx.ui.present.error(f"Failed to launch Multipass test: {exc}")
            raise typer.Exit(1)

        if result.returncode != 0:
            ctx.ui.present.error(f"`pytest` exited with {result.returncode}")
            raise typer.Exit(result.returncode)

    return app
