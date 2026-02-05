"""Remote run orchestration helpers for RunService."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from lb_controller.api import (
    BenchmarkController,
    ControllerOptions,
    StopToken,
    apply_playbook_defaults,
    pending_exists,
)
from lb_plugins.api import apply_plugin_assets

from lb_app.services.run_pipeline import maybe_start_event_tailer
from lb_app.services.run_types import RunContext, RunResult, _RemoteSession
from lb_app.services.run_output import AnsibleOutputFormatter
from lb_app.ui_interfaces import UIAdapter

if TYPE_CHECKING:
    from lb_app.services.interfaces import IRunService


class ControllerLogHandlers:
    """Attach controller log handlers and ensure cleanup."""

    def __init__(
        self, service: IRunService, context: RunContext, session: _RemoteSession
    ) -> None:
        self._service = service
        self._context = context
        self._session = session
        self._handlers: list[logging.Handler | None] = []

    def __enter__(self) -> "ControllerLogHandlers":
        jsonl_handler = self._service._attach_controller_jsonl(
            self._context, self._session
        )
        loki_handler = self._service._attach_controller_loki(
            self._context, self._session
        )
        self._handlers = [jsonl_handler, loki_handler]
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        for handler in self._handlers:
            if not handler:
                continue
            logging.getLogger().removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        self._handlers = []


class RemoteRunCoordinator:
    """Coordinate remote execution steps for RunService."""

    def __init__(self, service: IRunService) -> None:
        self._service = service

    def run(
        self,
        context: RunContext,
        run_id: str | None,
        output_callback: Callable[[str, str], None],
        formatter: AnsibleOutputFormatter | None,
        ui_adapter: UIAdapter | None,
        *,
        stop_token: StopToken | None,
        emit_timing: bool,
    ) -> RunResult:
        apply_playbook_defaults(context.config)
        if not context.config.plugin_assets:
            apply_plugin_assets(context.config, context.registry)
        session = self._service._prepare_remote_session(
            context, run_id, ui_adapter, stop_token
        )

        with ControllerLogHandlers(self._service, context, session):
            if not session.stop_token.should_stop() and not pending_exists(
                session.journal,
                context.target_tests,
                context.config.remote_hosts or [],
                context.config.repetitions,
                allow_skipped=session.resume_requested,
            ):
                return self._service._short_circuit_empty_run(
                    context, session, ui_adapter
                )

            pipeline = self._service._build_event_pipeline(
                context, session, formatter, output_callback, ui_adapter, emit_timing
            )

            controller = BenchmarkController(
                context.config,
                ControllerOptions(
                    output_callback=pipeline.output_cb,
                    output_formatter=formatter,
                    journal_refresh=(
                        session.dashboard.refresh if session.dashboard else None
                    ),
                    stop_token=session.stop_token,
                    state_machine=session.controller_state,
                ),
            )
            pipeline.controller_ref["controller"] = controller
            if formatter:
                formatter.host_label = ",".join(
                    h.name for h in context.config.remote_hosts
                )

            tailer = maybe_start_event_tailer(
                controller,
                pipeline.event_from_payload,
                pipeline.ingest_event,
                formatter,
            )

            summary = self._service._run_controller_loop(
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
