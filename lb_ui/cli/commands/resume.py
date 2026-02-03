from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Sequence, Tuple

import typer

import json
from datetime import datetime

from lb_app.api import RunJournal, RunRequest, RunStatus, results_exist_for_run
from lb_common.api import RunInfo
from lb_ui.presenters.plan import build_run_plan_table
from lb_ui.cli.commands.run_helpers import print_run_journal_summary, resolve_stop_file
from lb_ui.tui.system.models import PickItem
from lb_ui.wiring.dependencies import UIContext


def register_resume_command(app: typer.Typer, ctx: UIContext) -> None:
    """Register the resume command on the given Typer app."""

    def _load_config(config_path: Optional[Path]):
        cfg, resolved, stale = ctx.config_service.load_for_read(config_path)
        if stale:
            ctx.ui.present.warning(f"Saved default config not found: {stale}")
        if resolved:
            ctx.ui.present.success(f"Loaded config: {resolved}")
        else:
            ctx.ui.present.warning("No config file found; using built-in defaults.")
        return cfg

    def _load_journal(journal_path: Path) -> RunJournal | None:
        if not journal_path.exists():
            return None
        try:
            return RunJournal.load(journal_path)
        except Exception:
            return None

    def _load_journal_data(journal_path: Path) -> dict:
        if not journal_path.exists():
            return {}
        try:
            return json.loads(journal_path.read_text())
        except Exception:
            return {}

    def _extract_created_at(journal_data: dict) -> Optional[datetime]:
        if not isinstance(journal_data, dict):
            return None
        metadata = journal_data.get("metadata", journal_data)
        created_raw = metadata.get("created_at")
        if not isinstance(created_raw, str):
            return None
        try:
            return datetime.fromisoformat(created_raw)
        except Exception:
            return None

    def _extract_hosts_workloads(journal_data: dict) -> tuple[set[str], set[str]]:
        hosts: set[str] = set()
        workloads: set[str] = set()
        tasks = journal_data.get("tasks") if isinstance(journal_data, dict) else None
        if not isinstance(tasks, list):
            return hosts, workloads
        for task in tasks:
            if not isinstance(task, dict):
                continue
            host = task.get("host")
            workload = task.get("workload")
            if isinstance(host, str):
                hosts.add(host)
            if isinstance(workload, str):
                workloads.add(workload)
        return hosts, workloads

    def _fallback_hosts(output_root: Path) -> set[str]:
        return {entry.name for entry in output_root.iterdir() if entry.is_dir()}

    def _fallback_workloads(output_root: Path, hosts: set[str]) -> set[str]:
        if not hosts:
            return set()
        first_host = next(iter(hosts))
        host_root = output_root / first_host
        if not host_root.exists():
            return set()
        return {
            entry.name
            for entry in host_root.iterdir()
            if entry.is_dir() and not entry.name.startswith("_")
        }

    def _build_run_info(output_root: Path) -> RunInfo:
        journal_path = output_root / "run_journal.json"
        journal = _load_journal(journal_path)
        if journal:
            created_at = _extract_created_at(journal.metadata if journal.metadata else {})
            hosts = {task.host for task in journal.tasks.values()}
            workloads = {task.workload for task in journal.tasks.values()}
        else:
            journal_data = _load_journal_data(journal_path)
            created_at = _extract_created_at(journal_data)
            hosts, workloads = _extract_hosts_workloads(journal_data)
        if not hosts:
            hosts = _fallback_hosts(output_root)
        if not workloads and hosts:
            workloads = _fallback_workloads(output_root, hosts)
        return RunInfo(
            run_id=output_root.name,
            output_root=output_root,
            report_root=None,
            data_export_root=None,
            hosts=sorted(hosts),
            workloads=sorted(workloads),
            created_at=created_at,
            journal_path=journal_path if journal_path.exists() else None,
        )

    def _discover_runs(output_root: Path) -> list[RunInfo]:
        if not output_root.exists():
            return []
        runs: list[RunInfo] = []
        for entry in output_root.iterdir():
            if entry.is_dir() and entry.name.startswith("run-"):
                runs.append(_build_run_info(entry))
        runs.sort(
            key=lambda r: (
                r.created_at.timestamp()
                if r.created_at
                else r.output_root.stat().st_mtime
            ),
            reverse=True,
        )
        return runs

    def _journal_status(run_info: RunInfo) -> Tuple[str, bool, str, Sequence[str]]:
        journal_path = run_info.journal_path or (run_info.output_root / "run_journal.json")
        if journal_path.exists():
            try:
                journal = RunJournal.load(journal_path)
            except Exception as exc:
                return "unknown", False, f"Journal error: {exc}", run_info.workloads
            if not journal.tasks:
                return "unknown", False, "Journal has no tasks", run_info.workloads
            pending = any(task.status != RunStatus.COMPLETED for task in journal.tasks.values())
            if pending:
                return "incomplete", False, "Pending or failed repetitions", run_info.workloads
            return "completed", True, "All repetitions completed", run_info.workloads

        if results_exist_for_run(run_info.output_root):
            return "unknown", False, "Journal missing; results found", run_info.workloads
        return "missing", True, "No journal or results found", run_info.workloads

    def _select_run_id(output_root: Path) -> tuple[str, Sequence[str]]:
        runs = _discover_runs(output_root)
        if not runs:
            ctx.ui.present.error(f"No runs found under {output_root}")
            raise typer.Exit(1)

        items: list[PickItem] = []
        for run in runs:
            status, disabled, note, workloads = _journal_status(run)
            label = run.run_id
            if status == "completed":
                label = f"{label} (completed)"
            elif status == "missing":
                label = f"{label} (no results)"
            desc_parts = []
            if run.created_at:
                desc_parts.append(run.created_at.isoformat())
            if workloads:
                desc_parts.append(f"workloads: {', '.join(workloads)}")
            if run.hosts:
                desc_parts.append(f"hosts: {', '.join(run.hosts)}")
            if note:
                desc_parts.append(note)
            description = " | ".join(desc_parts)
            items.append(
                PickItem(
                    id=run.run_id,
                    title=label,
                    description=description,
                    disabled=disabled,
                    payload=run,
                )
            )

        selection = ctx.ui.picker.pick_one(
            items,
            title="Select a run to resume",
            query_hint="run-",
        )
        if selection is None:
            raise typer.Exit(1)
        payload = selection.payload
        workloads = payload.workloads if payload and hasattr(payload, "workloads") else []
        return selection.id, workloads

    def _resolve_run_or_pick(
        run_id: Optional[str], output_root: Path
    ) -> tuple[str, Sequence[str]]:
        if run_id:
            run = next(
                (info for info in _discover_runs(output_root) if info.run_id == run_id),
                None,
            )
            if not run:
                ctx.ui.present.error(f"Run '{run_id}' not found under {output_root}")
                raise typer.Exit(1)
            status, disabled, note, workloads = _journal_status(run)
            if disabled:
                ctx.ui.present.error(
                    f"Run '{run_id}' is not resumable: {note or status}"
                )
                raise typer.Exit(1)
            return run_id, workloads

        if ctx.headless:
            ctx.ui.present.error("Resume requires a run-id when running headless.")
            raise typer.Exit(1)
        return _select_run_id(output_root)

    def _explicit_execution_mode(
        docker: bool, multipass: bool, remote: Optional[bool]
    ) -> Optional[str]:
        if docker:
            return "docker"
        if multipass:
            return "multipass"
        if remote is not None:
            return "remote"
        return None

    def _execution_mode_from_journal(output_root: Path, run_id: str) -> str:
        journal_path = output_root / run_id / "run_journal.json"
        if not journal_path.exists():
            ctx.ui.present.warning(
                f"Run '{run_id}' has no journal; cannot infer execution mode."
            )
            raise typer.Exit(1)
        journal = RunJournal.load(journal_path)
        mode = (journal.metadata or {}).get("execution_mode")
        if not mode:
            ctx.ui.present.warning(
                f"Run '{run_id}' has no execution mode metadata."
            )
            ctx.ui.present.error(
                "Specify --docker, --multipass, or --remote to resume."
            )
            raise typer.Exit(1)
        return str(mode).lower()

    def _node_count_from_journal(output_root: Path, run_id: str) -> int:
        journal_path = output_root / run_id / "run_journal.json"
        if not journal_path.exists():
            ctx.ui.present.warning(
                f"Run '{run_id}' has no journal; cannot infer node count."
            )
            ctx.ui.present.error(
                "Specify --nodes to resume docker or multipass runs."
            )
            raise typer.Exit(1)
        journal = RunJournal.load(journal_path)
        count = (journal.metadata or {}).get("node_count")
        if not count:
            ctx.ui.present.warning(
                f"Run '{run_id}' has no node count metadata."
            )
            ctx.ui.present.error(
                "Specify --nodes to resume docker or multipass runs."
            )
            raise typer.Exit(1)
        return int(count)

    @app.command("resume")
    def resume(
        run_id: Optional[str] = typer.Argument(
            None,
            help="Run identifier to resume; omit to select interactively.",
        ),
        config: Optional[Path] = typer.Option(
            None,
            "--config",
            "-c",
            help="Config file to load for resume.",
        ),
        root: Optional[Path] = typer.Option(
            None,
            "--root",
            "-r",
            help="Root directory containing benchmark_results run folders.",
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
        multipass: bool = typer.Option(
            False,
            "--multipass",
            help="Provision Multipass VMs (Ubuntu 24.04) and run benchmarks on them.",
        ),
        node_count: Optional[int] = typer.Option(
            None,
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
        intensity: Optional[str] = typer.Option(
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
        skip_connectivity_check: bool = typer.Option(
            False,
            "--skip-connectivity-check",
            help="Skip the pre-run SSH connectivity check for remote hosts.",
        ),
        connectivity_timeout: int = typer.Option(
            10,
            "--connectivity-timeout",
            help="Timeout in seconds for the SSH connectivity check.",
        ),
    ) -> None:
        """Resume a previous run and continue incomplete repetitions."""
        import time

        start_ts = time.time()
        from lb_common.api import configure_logging
        from lb_app.api import MAX_NODES

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

        if node_count is not None and node_count < 1:
            ctx.ui.present.error("Node count must be at least 1.")
            raise typer.Exit(1)
        if node_count is not None and node_count > MAX_NODES:
            ctx.ui.present.error(f"Maximum supported nodes is {MAX_NODES}.")
            raise typer.Exit(1)

        stop_file_resolved = resolve_stop_file(stop_file)

        cfg = _load_config(config)
        output_root = root or cfg.output_dir
        if root:
            cfg.output_dir = output_root

        selected_run_id, run_workloads = _resolve_run_or_pick(run_id, output_root)
        ctx.ui.present.info(f"Resuming run: {selected_run_id}")

        cfg.ensure_output_dirs()
        explicit_mode = _explicit_execution_mode(docker, multipass, remote)
        execution_mode = explicit_mode or _execution_mode_from_journal(
            output_root, selected_run_id
        )
        if explicit_mode is None:
            ctx.ui.present.info(f"Using execution mode from journal: {execution_mode}")

        resolved_node_count = node_count
        if execution_mode in ("docker", "multipass"):
            if resolved_node_count is None:
                resolved_node_count = _node_count_from_journal(
                    output_root, selected_run_id
                )
                ctx.ui.present.info(
                    f"Using node count from journal: {resolved_node_count}"
                )
            if resolved_node_count < 1:
                ctx.ui.present.error("Node count must be at least 1.")
                raise typer.Exit(1)
            if resolved_node_count > MAX_NODES:
                ctx.ui.present.error(f"Maximum supported nodes is {MAX_NODES}.")
                raise typer.Exit(1)
        else:
            resolved_node_count = len(cfg.remote_hosts or []) or 1

        plan_tests = list(run_workloads) if run_workloads else list(cfg.workloads.keys())
        if not plan_tests:
            ctx.ui.present.error("No workloads selected to run.")
            raise typer.Exit(1)

        from lb_ui.notifications import send_notification
        from lb_ui.services.tray import TrayManager

        tray = TrayManager()
        tray_enabled = not ctx.headless
        if tray_enabled:
            tray.start()

        result = None
        run_success = False
        try:
            request = RunRequest(
                config=cfg,
                tests=plan_tests,
                run_id=None,
                resume=selected_run_id,
                debug=debug,
                intensity=intensity,
                setup=setup,
                stop_file=stop_file_resolved,
                execution_mode=execution_mode,
                repetitions=None,
                node_count=resolved_node_count,
                docker_engine=docker_engine,
                ui_adapter=ctx.ui_adapter,
                skip_connectivity_check=skip_connectivity_check,
                connectivity_timeout=connectivity_timeout,
            )

            plan = ctx.app_client.get_run_plan(
                cfg,
                plan_tests,
                execution_mode=execution_mode,
            )
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

            run_result = ctx.app_client.start_run(request, _Hooks())
            if run_result is None:
                raise typer.Exit(1)
            result = run_result
            run_success = True
        except ValueError as e:
            ctx.ui.present.warning(str(e))
            raise typer.Exit(1)
        except Exception as exc:
            ctx.ui.present.error(f"Resume failed: {exc}")
            raise typer.Exit(1)
        finally:
            if tray_enabled:
                tray.stop()

            total_duration = time.time() - start_ts
            if not ctx.headless:
                status_word = "SUCCESS" if run_success else "FAILED"
                msg_body = f"Benchmark execution finished with status: {status_word}"

                send_notification(
                    title=f"Benchmark {status_word}",
                    message=msg_body,
                    success=run_success,
                    run_id=selected_run_id,
                    duration_s=total_duration,
                )

        if (
            result
            and result.journal_path
            and os.getenv("LB_SUPPRESS_SUMMARY", "").lower() not in ("1", "true", "yes")
        ):
            print_run_journal_summary(
                ctx,
                result.journal_path,
                log_path=result.log_path,
                ui_log_path=result.ui_log_path,
            )

        ctx.ui.present.success("Resume completed.")
