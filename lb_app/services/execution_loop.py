"Core execution loop for the benchmark controller."

from __future__ import annotations

import queue
import threading
import time
from typing import TYPE_CHECKING, Any

from lb_controller.api import (
    BenchmarkController,
    ControllerRunner,
    DoubleCtrlCStateMachine,
    RunExecutionSummary,
    SigintDoublePressHandler,
    RunStatus,
)
from lb_app.services.run_logging import (
    emit_warning,
    log_completion,
    on_controller_state_change,
)
from lb_app.services.run_system_info import attach_system_info
from lb_app.services.run_types import (
    RunContext,
    _EventPipeline,
    _RemoteSession,
    _SignalContext,
)

if TYPE_CHECKING:
    from lb_app.ui_interfaces import UIAdapter


class RunExecutionLoop:
    """Manages the main execution loop, signal handling, and lifecycle events."""

    def run_loop(
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
        self,
        session: _RemoteSession,
        ui_adapter: UIAdapter | None,
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
        session: _SignalContext,
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
    
    @staticmethod
    def _fail_running_tasks(journal: Any, reason: str = "stopped") -> None:
         """Mark any RUNNING tasks as FAILED with the given reason."""
         # Note: RunJournal type imported but here treating as Any to avoid strict circular import if not careful,
         # but we can import RunJournal if needed.
         for task in journal.tasks.values():
             if task.status == RunStatus.RUNNING:
                 task.status = RunStatus.FAILED
                 task.current_action = reason
                 task.error = reason
