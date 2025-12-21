"""Application-facing run orchestration helpers for the CLI."""

from __future__ import annotations

import time
import threading
import queue
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Callable, Dict, List, Optional

from lb_runner.api import BenchmarkConfig, PluginRegistry
from lb_runner.stop_token import StopToken
from lb_controller.api import (
    ControllerRunner,
    ControllerStateMachine,
    DoubleCtrlCStateMachine,
    LogSink,
    RunJournal,
    RunStatus,
    SigintDoublePressHandler,
    pending_exists,
)
from lb_app.ui_interfaces import UIAdapter, DashboardHandle, NoOpDashboardHandle

if TYPE_CHECKING:
    from lb_controller.api import BenchmarkController, RunExecutionSummary
from lb_app.services.run_journal import (
    build_journal_from_results,
    find_latest_journal,
    generate_run_id,
    initialize_new_journal,
    load_resume_journal,
)
from lb_app.services.run_logging import (
    announce_stop_factory,
    emit_warning,
    log_completion,
    on_controller_state_change,
)
from lb_app.services.run_pipeline import (
    event_from_payload_data,
    make_ingest_event,
    make_output_tee,
    make_progress_handler,
    maybe_start_event_tailer,
    parse_progress_line,
    pipeline_output_callback,
)
from lb_app.services.run_output import (  # noqa: F401
    AnsibleOutputFormatter,
    _extract_lb_event_data,
)
from lb_app.services.run_plan import build_run_plan
from lb_app.services.run_system_info import attach_system_info
from lb_app.services.run_types import (
    RunContext,
    RunResult,
    _RemoteSession,
    _EventPipeline,
    _SignalContext,
    _EventDedupe,
    _DashboardLogProxy,
)


class RunService:
    """Coordinate benchmark execution for CLI commands."""

    def __init__(self, registry_factory: Callable[[], PluginRegistry]):
        self._registry_factory = registry_factory
        self._progress_token = "LB_EVENT"

    def _enable_dashboard_log(
        self,
        dashboard: DashboardHandle,
        journal_path: Path,
    ) -> tuple[DashboardHandle, Path | None, IO[str] | None]:
        """Attach a ui_stream.log file to the dashboard when available."""
        if isinstance(dashboard, NoOpDashboardHandle):
            return dashboard, None, None
        ui_stream_log_path = journal_path.parent / "ui_stream.log"
        try:
            ui_stream_log_file = ui_stream_log_path.open("a", encoding="utf-8")
        except Exception:
            return dashboard, None, None
        wrapped = _DashboardLogProxy(dashboard, ui_stream_log_file)
        return wrapped, ui_stream_log_path, ui_stream_log_file

    def get_run_plan(
        self,
        cfg: BenchmarkConfig,
        tests: List[str],
        execution_mode: str = "remote",
        registry: PluginRegistry | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Build a detailed plan for the workloads to be run.

        Returns a list of dictionaries containing status, intensity, details, etc.
        """
        registry = registry or self._registry_factory()
        return build_run_plan(
            cfg,
            tests,
            execution_mode=execution_mode,
            registry=registry,
        )

    @staticmethod
    def apply_overrides(
        cfg: BenchmarkConfig, intensity: str | None, debug: bool
    ) -> None:
        """Apply CLI-driven overrides to the configuration."""
        if intensity:
            for wl_name in cfg.workloads:
                cfg.workloads[wl_name].intensity = intensity
        if debug:
            for workload in cfg.workloads.values():
                if isinstance(workload.options, dict):
                    workload.options["debug"] = True
                else:
                    try:
                        setattr(workload.options, "debug", True)
                    except Exception:
                        pass

    def build_context(
        self,
        cfg: BenchmarkConfig,
        tests: Optional[List[str]],
        config_path: Optional[Path] = None,
        debug: bool = False,
        resume: Optional[str] = None,
        stop_file: Optional[Path] = None,
        execution_mode: str = "remote",
    ) -> RunContext:
        """Compute the run context and registry."""
        registry = self._registry_factory()
        target_tests = tests or [
            name for name, workload in cfg.workloads.items() if workload.enabled
        ]
        return RunContext(
            config=cfg,
            target_tests=target_tests,
            registry=registry,
            config_path=config_path,
            debug=debug,
            resume_from=None if resume in (None, "latest") else resume,
            resume_latest=resume == "latest",
            stop_file=stop_file,
            execution_mode=execution_mode,
        )

    def create_session(
        self,
        config_service: Any,
        tests: Optional[List[str]] = None,
        config_path: Optional[Path] = None,
        run_id: Optional[str] = None,
        resume: Optional[str] = None,
        repetitions: Optional[int] = None,
        debug: bool = False,
        intensity: Optional[str] = None,
        ui_adapter: UIAdapter | None = None,
        setup: bool = True,
        stop_file: Optional[Path] = None,
        execution_mode: str = "remote",
        preloaded_config: BenchmarkConfig | None = None,
    ) -> RunContext:
        """
        Orchestrate the creation of a RunContext from raw inputs.

        This method consolidates configuration loading, overrides, and context building.
        """
        cfg, resolved = self._load_or_default_config(
            config_service, config_path, ui_adapter, preloaded_config
        )
        self._apply_setup_overrides(
            cfg, setup, repetitions, intensity, ui_adapter, debug
        )
        target_tests = self._resolve_target_tests(cfg, tests)
        context = self.build_context(
            cfg,
            target_tests,
            config_path=resolved,
            debug=debug,
            resume=resume,
            stop_file=stop_file,
            execution_mode=execution_mode,
        )
        return context

    def _load_or_default_config(
        self,
        config_service: Any,
        config_path: Optional[Path],
        ui_adapter: UIAdapter | None,
        preloaded_config: BenchmarkConfig | None,
    ) -> tuple[BenchmarkConfig, Optional[Path]]:
        """Load config from disk or return a provided instance with UI feedback."""
        if preloaded_config is not None:
            return preloaded_config, config_path
        cfg, resolved, stale = config_service.load_for_read(config_path)
        if ui_adapter:
            if stale:
                ui_adapter.show_warning(f"Saved default config not found: {stale}")
            if resolved:
                ui_adapter.show_success(f"Loaded config: {resolved}")
            else:
                ui_adapter.show_warning(
                    "No config file found; using built-in defaults."
                )
        return cfg, resolved

    def _apply_setup_overrides(
        self,
        cfg: BenchmarkConfig,
        setup: bool,
        repetitions: Optional[int],
        intensity: Optional[str],
        ui_adapter: UIAdapter | None,
        debug: bool,
    ) -> None:
        """Apply CLI flags to config and ensure directories exist."""
        cfg.remote_execution.run_setup = setup
        if not setup:
            cfg.remote_execution.run_teardown = False
        cfg.remote_execution.enabled = True
        if repetitions is not None:
            cfg.repetitions = repetitions
            if ui_adapter:
                ui_adapter.show_info(f"Using {repetitions} repetitions for this run")
        self.apply_overrides(cfg, intensity=intensity, debug=debug)
        if intensity and ui_adapter:
            ui_adapter.show_info(f"Global intensity override: {intensity}")
        cfg.ensure_output_dirs()

    @staticmethod
    def _resolve_target_tests(
        cfg: BenchmarkConfig, tests: Optional[List[str]]
    ) -> List[str]:
        """Determine which workloads to run, raising if none are enabled/selected."""
        target_tests = tests or [
            name for name, wl in cfg.workloads.items() if wl.enabled
        ]
        if not target_tests:
            raise ValueError("No workloads selected to run.")
        return target_tests

    def execute(
        self,
        context: RunContext,
        run_id: Optional[str],
        output_callback: Optional[Callable[[str, str], None]] = None,
        ui_adapter: UIAdapter | None = None,
    ) -> RunResult:
        """Execute benchmarks using remote hosts provisioned upstream."""
        if not context.config.remote_hosts:
            raise ValueError(
                "No remote hosts available. Provision nodes before running benchmarks."
            )

        stop_token = StopToken(stop_file=context.stop_file, enable_signals=False)
        formatter = AnsibleOutputFormatter()
        formatter.emit_task_timings = False
        formatter.emit_task_starts = False
        callback = output_callback
        emit_timing = False
        if callback is None:
            if context.debug:
                # In debug mode, print everything raw for troubleshooting
                def _debug_printer(text: str, end: str = ""):
                    print(text, end=end, flush=True)

                callback = _debug_printer
            else:
                callback = formatter.process

        return self._run_remote(
            context,
            run_id,
            callback,
            formatter,
            ui_adapter,
            stop_token=stop_token,
            emit_timing=emit_timing,
        )

    def _run_remote(
        self,
        context: RunContext,
        run_id: Optional[str],
        output_callback: Callable[[str, str], None],
        formatter: AnsibleOutputFormatter | None,
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None = None,
        emit_timing: bool = True,
    ) -> RunResult:
        """Execute a remote run using the controller with journal integration."""
        from lb_controller.api import (
            BenchmarkController,
        )  # Runtime import to break circular dependency

        session = self._prepare_remote_session(context, run_id, ui_adapter, stop_token)

        if not session.stop_token.should_stop() and not pending_exists(
            session.journal,
            context.target_tests,
            context.config.remote_hosts or [],
            context.config.repetitions,
        ):
            return self._short_circuit_empty_run(context, session, ui_adapter)

        pipeline = self._build_event_pipeline(
            context, session, formatter, output_callback, ui_adapter, emit_timing
        )

        controller = BenchmarkController(
            context.config,
            output_callback=pipeline.output_cb,
            output_formatter=formatter,
            journal_refresh=session.dashboard.refresh if session.dashboard else None,
            stop_token=session.stop_token,
            state_machine=session.controller_state,
        )
        pipeline.controller_ref["controller"] = controller
        if formatter:
            formatter.host_label = ",".join(h.name for h in context.config.remote_hosts)

        tailer = maybe_start_event_tailer(
            controller, pipeline.event_from_payload, pipeline.ingest_event, formatter
        )

        summary = self._run_controller_loop(
            controller=controller,
            context=context,
            session=session,
            pipeline=pipeline,
            ui_adapter=ui_adapter,
        )

        if tailer:
            tailer.stop()
        session.sink.close()
        session.stop_token.restore()
        return RunResult(
            context=context,
            summary=summary,
            journal_path=session.journal_path,
            log_path=session.log_path,
            ui_log_path=session.ui_stream_log_path,
        )

    def _prepare_remote_session(
        self,
        context: RunContext,
        run_id: Optional[str],
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None,
    ) -> _RemoteSession:
        """Initialize journal, dashboard, log files, and session state."""
        ui_stream_log_file: IO[str] | None = None
        stop = stop_token or StopToken(
            stop_file=context.stop_file, enable_signals=False
        )
        resume_requested = context.resume_from is not None or context.resume_latest
        journal, journal_path, dashboard, effective_run_id = (
            self._prepare_journal_and_dashboard(
                context, run_id, ui_adapter, ui_stream_log_file
            )
        )
        log_path = journal_path.parent / "run.log"
        log_file = log_path.open("a", encoding="utf-8")
        dashboard, ui_stream_log_path, ui_stream_log_file = self._enable_dashboard_log(
            dashboard, journal_path
        )
        sink = LogSink(journal, journal_path, log_path)
        return _RemoteSession(
            journal=journal,
            journal_path=journal_path,
            dashboard=dashboard,
            ui_stream_log_file=ui_stream_log_file,
            ui_stream_log_path=ui_stream_log_path,
            log_path=log_path,
            log_file=log_file,
            sink=sink,
            stop_token=stop,
            effective_run_id=effective_run_id,
            controller_state=ControllerStateMachine(),
            resume_requested=resume_requested,
        )

    def _short_circuit_empty_run(
        self, context: RunContext, session: _RemoteSession, ui_adapter: UIAdapter | None
    ) -> RunResult:
        """Handle resume cases where nothing remains to run."""
        msg = "All repetitions already completed; nothing to run."
        try:
            session.log_file.write(msg + "\n")
            session.log_file.flush()
        except Exception:
            pass
        session.sink.close()
        try:
            session.log_file.close()
        except Exception:
            pass
        if session.ui_stream_log_file:
            try:
                session.ui_stream_log_file.close()
            except Exception:
                pass
        if ui_adapter:
            ui_adapter.show_info(msg)
        session.stop_token.restore()
        return RunResult(
            context=context,
            summary=None,
            journal_path=session.journal_path,
            log_path=session.log_path,
            ui_log_path=session.ui_stream_log_path,
        )

    def _build_event_pipeline(
        self,
        context: RunContext,
        session: _RemoteSession,
        formatter: AnsibleOutputFormatter | None,
        output_callback: Callable[[str, str], None],
        ui_adapter: UIAdapter | None,
        emit_timing: bool,
    ) -> _EventPipeline:
        """Wire output handlers, dedupe, and dashboard logging."""
        dashboard = session.dashboard
        output_cb = pipeline_output_callback(
            dashboard=dashboard, formatter=formatter, output_callback=output_callback
        )
        timing_handler: Callable[[str], None] | None = None
        if emit_timing and formatter and output_callback is not formatter.process:
            def _timing_sink(message: str) -> None:
                output_cb(message, end="\n")

            def _timing_handler(line: str) -> None:
                formatter.process_timing(line, log_sink=_timing_sink)

            timing_handler = _timing_handler
        announce_stop = announce_stop_factory(session, ui_adapter)
        session.stop_token._on_stop = announce_stop  # type: ignore[attr-defined]

        controller_ref: dict[str, BenchmarkController | None] = {"controller": None}
        dedupe = _EventDedupe()
        ingest_event = make_ingest_event(
            session=session,
            dashboard=dashboard,
            controller_ref=controller_ref,
            dedupe=dedupe,
        )
        event_from_payload = lambda data: event_from_payload_data(data, session, context)
        progress_handler = make_progress_handler(
            session=session,
            context=context,
            ingest_event=ingest_event,
            progress_token=self._progress_token,
        )
        output_with_progress = make_output_tee(
            session=session,
            downstream=output_cb,
            progress_handler=progress_handler,
            timing_handler=timing_handler,
        )

        if session.stop_token.should_stop():
            announce_stop()

        return _EventPipeline(
            output_cb=output_with_progress,
            announce_stop=announce_stop,
            ingest_event=ingest_event,
            event_from_payload=event_from_payload,
            sink=session.sink,
            controller_ref=controller_ref,
        )

    def _run_controller_loop(
        self,
        controller: BenchmarkController,
        context: RunContext,
        session: _RemoteSession,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None,
    ) -> RunExecutionSummary | None:
        """Drive the controller runner with signal handling and logging."""
        runner = self._build_controller_runner(controller, context, session, ui_adapter)
        signals = self._build_signal_context(session, ui_adapter)
        try:
            summary, elapsed = self._drive_runner(
                runner, session, signals, pipeline, ui_adapter=ui_adapter
            )
            self._handle_run_completion(
                summary=summary,
                elapsed=elapsed,
                context=context,
                session=session,
                pipeline=pipeline,
                ui_adapter=ui_adapter,
            )
        finally:
            self._cleanup_signal_context(signals)
            try:
                session.log_file.close()
            except Exception:
                pass
            if session.ui_stream_log_file:
                try:
                    session.ui_stream_log_file.close()
                except Exception:
                    pass
        return summary

    def _build_controller_runner(
        self,
        controller: BenchmarkController,
        context: RunContext,
        session: _RemoteSession,
        ui_adapter: UIAdapter | None,
    ) -> ControllerRunner:
        """Create the controller runner with state-change callbacks."""
        return ControllerRunner(
            run_callable=lambda: controller.run(
                context.target_tests,
                run_id=session.effective_run_id,
                journal=session.journal,
                resume=session.resume_requested,
                journal_path=session.journal_path,
            ),
            stop_token=session.stop_token,
            on_state_change=lambda new, reason: on_controller_state_change(
                new, reason, session, ui_adapter
            ),
            state_machine=session.controller_state,
        )

    def _build_signal_context(
        self, session: _RemoteSession, ui_adapter: UIAdapter | None
    ) -> _SignalContext:
        """Initialize SIGINT handling primitives for the run loop."""
        ctx = _SignalContext(
            events=queue.SimpleQueue(), state_machine=DoubleCtrlCStateMachine()
        )
        ctx.state_machine.reset_arm()
        return ctx

    def _drive_runner(
        self,
        runner: ControllerRunner,
        session: _RemoteSession,
        signals: _SignalContext,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None = None,
    ) -> tuple[RunExecutionSummary | None, float]:
        """Run controller loop, honoring double-SIGINT semantics."""

        def _run_active() -> bool:
            return not session.controller_state.is_terminal()

        start_ts = time.monotonic()
        summary: RunExecutionSummary | None = None

        with (
            session.dashboard.live(),
            SigintDoublePressHandler(
                state_machine=signals.state_machine,
                run_active=_run_active,
                on_first_sigint=lambda: signals.events.put(("warn", None)),
                on_confirmed_sigint=lambda: signals.events.put(
                    ("stop", "User requested stop")
                ),
            ),
        ):
            runner.start()
            while True:
                self._drain_ctrlc_events(
                    runner, session, signals, pipeline, ui_adapter=ui_adapter
                )
                candidate = runner.wait(timeout=0.2)
                if candidate is not None:
                    summary = candidate
                    break
        elapsed = time.monotonic() - start_ts
        return summary, elapsed

    def _drain_ctrlc_events(
        self,
        runner: ControllerRunner,
        session: _RemoteSession,
        signals: _SignalContext,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None = None,
    ) -> None:
        """Process pending SIGINT events."""
        while True:
            try:
                kind, reason = signals.events.get_nowait()
            except queue.Empty:
                return
            if kind == "warn":
                self._log_arm_warning(session, signals, ui_adapter)
            elif kind == "stop":
                runner.arm_stop(reason or "User requested stop")
                pipeline.announce_stop()

    def _log_arm_warning(
        self,
        session: _RemoteSession,
        signals: _SignalContext,
        ui_adapter: UIAdapter | None,
    ) -> None:
        """Emit and schedule clearance for the first Ctrl+C warning."""
        msg = "Press Ctrl+C again to stop the execution"
        emit_warning(
            msg,
            dashboard=session.dashboard,
            ui_adapter=ui_adapter,
            log_file=session.log_file,
            ui_stream_log_file=session.ui_stream_log_file,
            ttl=10.0,
        )
        if signals.warning_timer and signals.warning_timer.is_alive():
            signals.warning_timer.cancel()

        def _clear_warning() -> None:
            signals.state_machine.reset_arm()
            if session.dashboard and hasattr(session.dashboard, "clear_warning"):
                try:
                    session.dashboard.clear_warning()
                    session.dashboard.refresh()
                except Exception:
                    pass

        timer = threading.Timer(10.0, _clear_warning)
        timer.daemon = True
        timer.start()
        signals.warning_timer = timer

    def _handle_run_completion(
        self,
        summary: RunExecutionSummary | None,
        elapsed: float,
        context: RunContext,
        session: _RemoteSession,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None,
    ) -> None:
        """Finalize run, surface results, and attach metadata."""
        log_completion(elapsed, session, ui_adapter)
        if session.stop_token.should_stop():
            self._on_stop_requested(summary, session, pipeline, ui_adapter)
        self._attach_and_log_system_info(context, session, ui_adapter)

    def _on_stop_requested(
        self,
        summary: RunExecutionSummary | None,
        session: _RemoteSession,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None,
    ) -> None:
        """Handle teardown when a stop was requested."""
        pipeline.announce_stop()
        self._fail_running_tasks(session.journal, reason="stopped")
        session.journal.save(session.journal_path)
        if summary is None:
            return
        failed_teardowns = [
            name
            for name, res in summary.phases.items()
            if name.startswith("teardown") and not res.success
        ]
        if not failed_teardowns:
            return
        err = (
            "Teardown failed ("
            + ", ".join(failed_teardowns)
            + "); remote workloads may still be running."
        )
        if ui_adapter:
            ui_adapter.show_error(err)
        elif session.dashboard:
            session.dashboard.add_log(f"[red]{err}[/red]")
            session.dashboard.refresh()
        else:
            print(err)
        try:
            session.log_file.write(err + "\n")
            session.log_file.flush()
        except Exception:
            pass

    def _attach_and_log_system_info(
        self,
        context: RunContext,
        session: _RemoteSession,
        ui_adapter: UIAdapter | None,
    ) -> None:
        """Attach system info summaries to journal and UI if present."""
        output_root = session.journal_path.parent
        hosts = (
            [h.name for h in context.config.remote_hosts]
            if context.config.remote_hosts
            else ["localhost"]
        )
        if attach_system_info(
            session.journal,
            output_root,
            hosts,
            session.dashboard,
            ui_adapter,
            session.log_file,
        ):
            session.journal.save(session.journal_path)
        if session.dashboard:
            session.dashboard.refresh()

    @staticmethod
    def _cleanup_signal_context(signals: _SignalContext) -> None:
        """Ensure timers are cancelled after the run."""
        if signals.warning_timer and signals.warning_timer.is_alive():
            signals.warning_timer.cancel()

    def _prepare_journal_and_dashboard(
        self,
        context: RunContext,
        run_id: Optional[str],
        ui_adapter: UIAdapter | None,
        ui_stream_log_file: IO[str] | None = None,
    ) -> tuple[RunJournal, Path, DashboardHandle, str]:
        """Load or create the run journal and optional dashboard."""
        resume_requested = context.resume_from is not None or context.resume_latest
        if resume_requested:
            journal, journal_path, run_identifier = self._load_resume_journal(
                context, run_id
            )
        else:
            journal, journal_path, run_identifier = self._initialize_new_journal(
                context, run_id
            )

        # Persist the initial state so resume is possible even if execution aborts early
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal.save(journal_path)

        # Default stop file lives next to the journal.
        if context.stop_file is None:
            context.stop_file = journal_path.parent / "STOP"

        dashboard = self._create_dashboard(
            context, ui_adapter, journal, ui_stream_log_file
        )

        return journal, journal_path, dashboard, run_identifier

    def _load_resume_journal(
        self, context: RunContext, run_id: Optional[str]
    ) -> tuple[RunJournal, Path, str]:
        """Load an existing journal and reconcile configuration for resume."""
        return load_resume_journal(context, run_id)

    def _initialize_new_journal(
        self, context: RunContext, run_id: Optional[str]
    ) -> tuple[RunJournal, Path, str]:
        """Create a fresh journal for a new run."""
        return initialize_new_journal(context, run_id)

    def _create_dashboard(
        self,
        context: RunContext,
        ui_adapter: UIAdapter | None,
        journal: RunJournal,
        ui_stream_log_file: IO[str] | None,
    ) -> DashboardHandle:
        """Build a dashboard handle or a no-op substitute."""
        if not ui_adapter:
            return NoOpDashboardHandle()
        plan = self.get_run_plan(
            context.config,
            context.target_tests,
            execution_mode=context.execution_mode,
            registry=context.registry,
        )
        return ui_adapter.create_dashboard(plan, journal, ui_stream_log_file)

    def _build_journal_from_results(
        self,
        run_id: str,
        context: RunContext,
        host_name: str,
    ) -> RunJournal:
        """Construct a RunJournal from existing *_results.json artifacts when missing."""
        return build_journal_from_results(run_id, context, host_name)

    @staticmethod
    def _find_latest_journal(config: BenchmarkConfig) -> Path | None:
        """Return the most recent journal path if present."""
        return find_latest_journal(config)

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a timestamped run id matching the controller's format."""
        return generate_run_id()

    def _parse_progress_line(self, line: str) -> dict[str, Any] | None:
        """Parse progress markers emitted by LocalRunner."""
        return parse_progress_line(line, token=self._progress_token)

    @staticmethod
    def _fail_running_tasks(journal: RunJournal, reason: str = "stopped") -> None:
        """Mark any RUNNING tasks as FAILED with the given reason."""
        for task in journal.tasks.values():
            if task.status == RunStatus.RUNNING:
                task.status = RunStatus.FAILED
                task.current_action = reason
                task.error = reason
