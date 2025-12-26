from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Callable

import typer

from lb_app.api import MAX_NODES
from lb_ui.wiring.dependencies import UIContext
from lb_ui.presenters.plan import build_run_plan_table
from lb_ui.presenters.journal import build_journal_table


def register_run_command(
    app: typer.Typer,
    ctx: UIContext,
) -> None:
    """Register the main run command on the given Typer app."""

    def _print_run_journal_summary(
        journal_path: Path,
        log_path: Path | None = None,
        ui_log_path: Path | None = None,
    ) -> None:
        """Load and render a completed run journal, with log hints."""
        try:
            from lb_app.api import RunJournal
            journal = RunJournal.load(journal_path)
        except Exception as exc:
            ctx.ui.present.warning(f"Could not read run journal at {journal_path}: {exc}")
            if log_path:
                ctx.ui.present.info(f"Ansible output log: {log_path}")
            return

        ctx.ui.tables.show(build_journal_table(journal))

        ctx.ui.present.info(f"Journal saved to {journal_path}")
        if log_path:
            ctx.ui.present.info(f"Ansible output log saved to {log_path}")
        if ui_log_path:
            ctx.ui.present.info(f"Dashboard log stream saved to {ui_log_path}")

    @app.command("run")
    def run(
        tests: List[str] = typer.Argument(
            None,
            help="Workload names to run; defaults to enabled workloads in the config.",
        ),
        config: Optional[Path] = typer.Option(
            None,
            "--config",
            "-c",
            help="Config file to load; uses saved default or local benchmark_config.json when omitted.",
        ),
        run_id: Optional[str] = typer.Option(
            None,
            "--run-id",
            help="Optional run identifier for tracking results.",
        ),
        resume: Optional[str] = typer.Option(
            None,
            "--resume",
            help="Resume a previous run; omit value to resume the latest.",
            flag_value="latest",
        ),
        remote: Optional[bool] = typer.Option(
            None,
            "--remote/--no-remote",
            help="Override remote execution from the config (local mode is not supported).",
        ),
        docker: bool = typer.Option(
            False,
            "--docker",
            help="Provision containers (Ubuntu 24.04) and run via Ansible.",
        ),
        docker_engine: str = typer.Option(
            "docker",
            "--docker-engine",
            help="Container engine to use with --docker (docker or podman).",
        ),
        repetitions: Optional[int] = typer.Option(
            None,
            "--repetitions",
            "-r",
            help="Override the number of repetitions for this run (must be >= 1).",
        ),
        multipass: bool = typer.Option(
            False,
            "--multipass",
            help="Provision Multipass VMs (Ubuntu 24.04) and run benchmarks on them.",
        ),
        node_count: int = typer.Option(
            1,
            "--nodes",
            "--multipass-vm-count",
            help="Number of containers/VMs to provision (max 2).",
        ),
        debug: bool = typer.Option(
            False,
            "--debug",
            help="Enable verbose debug logging (sets fio.debug=True when applicable).",
        ),
        stop_file: Optional[Path] = typer.Option(
            None,
            "--stop-file",
            help="Path to a stop sentinel file; when created, the run will stop gracefully.",
        ),
        intensity: str = typer.Option(
            None,
            "--intensity",
            "-i",
            help="Override workload intensity (low, medium, high, user_defined).",
        ),
        setup: bool = typer.Option(
            True,
            "--setup/--no-setup",
            help="Run environment setup (Global + Workload) before execution.",
        ),
    ) -> None:
        """Run workloads using Ansible on remote, Docker, or Multipass targets."""
        from lb_common.api import configure_logging

        if not ctx.dev_mode and (docker or multipass):
            ctx.ui.present.error("--docker and --multipass are available only in dev mode.")
            raise typer.Exit(1)

        if docker and multipass:
            ctx.ui.present.error("Choose either --docker or --multipass, not both.")
            raise typer.Exit(1)

        if remote is False and not docker and not multipass:
            ctx.ui.present.error(
                "Local execution has been removed; enable --remote, --docker, or --multipass."
            )
            raise typer.Exit(1)

        if debug:
            configure_logging(debug=True, force=True)
            ctx.ui.present.info("Debug logging enabled")

        if node_count < 1:
            ctx.ui.present.error("Node count must be at least 1.")
            raise typer.Exit(1)
        if node_count > MAX_NODES:
            ctx.ui.present.error(f"Maximum supported nodes is {MAX_NODES}.")
            raise typer.Exit(1)

        if repetitions is not None and repetitions < 1:
            ctx.ui.present.error("Repetitions must be at least 1.")
            raise typer.Exit(1)

        stop_file_resolved = stop_file or (
            Path(os.environ["LB_STOP_FILE"])
            if os.environ.get("LB_STOP_FILE")
            else None
        )

        cfg, resolved, stale = ctx.config_service.load_for_read(config)
        if stale:
            ctx.ui.present.warning(f"Saved default config not found: {stale}")
        if resolved:
            ctx.ui.present.success(f"Loaded config: {resolved}")
        else:
            ctx.ui.present.warning("No config file found; using built-in defaults.")

        cfg.ensure_output_dirs()

        execution_mode = "docker" if docker else "multipass" if multipass else "remote"

        result = None
        try:
            from lb_app.api import RunRequest

            selected_tests = tests or [name for name, wl in cfg.workloads.items() if wl.enabled]
            if not selected_tests:
                ctx.ui.present.error("No workloads selected to run.")
                ctx.ui.present.info("Enable workloads first with `lb plugin list --enable NAME` or use `lb config select-workloads`.")
                raise typer.Exit(1)

            run_request = RunRequest(
                config=cfg,
                tests=selected_tests,
                run_id=run_id,
                resume=resume,
                debug=debug,
                intensity=intensity,
                setup=setup,
                stop_file=stop_file_resolved,
                execution_mode=execution_mode,
                repetitions=repetitions,
                node_count=node_count,
                docker_engine=docker_engine,
                ui_adapter=ctx.ui_adapter,
            )

            plan = ctx.app_client.get_run_plan(cfg, selected_tests, execution_mode=execution_mode)
            ctx.ui.tables.show(build_run_plan_table(plan))

            class _Hooks:
                def on_log(self, line: str) -> None:
                    ctx.ui_adapter.show_info(line)

                def on_status(self, controller_state: str) -> None:
                    ctx.ui_adapter.show_info(f"Controller state: {controller_state}")

                def on_warning(self, message: str, ttl: float = 10.0) -> None:
                    ctx.ui_adapter.show_warning(message)

                def on_event(self, event) -> None:
                    pass

                def on_journal(self, journal) -> None:
                    pass

            run_result = ctx.app_client.start_run(run_request, _Hooks())
            result = run_result

        except ValueError as e:
            ctx.ui.present.warning(str(e))
            raise typer.Exit(1)
        except Exception as exc:
            ctx.ui.present.error(f"Run failed: {exc}")
            raise typer.Exit(1)

        if result and result.journal_path and os.getenv("LB_SUPPRESS_SUMMARY", "").lower() not in ("1", "true", "yes"):
            _print_run_journal_summary(result.journal_path, log_path=result.log_path, ui_log_path=result.ui_log_path)

        ctx.ui.present.success("Run completed.")
