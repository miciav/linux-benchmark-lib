"""Execution coordination helpers for remote runs."""

from __future__ import annotations

import logging
import platform
from typing import Callable

from lb_controller.api import BenchmarkController, RunEvent, StopToken

from lb_app.services.execution_loop import RunExecutionLoop
from lb_app.services.remote_run_coordinator import RemoteRunCoordinator
from lb_app.services.run_logging import announce_stop_factory
from lb_app.services.run_output import AnsibleOutputFormatter
from lb_app.services.run_pipeline import (
    event_from_payload_data,
    make_ingest_event,
    make_output_tee,
    make_progress_handler,
    parse_progress_line,
    pipeline_output_callback,
)
from lb_app.services.run_types import RunContext, RunResult, _EventDedupe, _EventPipeline, _RemoteSession
from lb_app.services.session_manager import SessionManager
from lb_app.ui_interfaces import UIAdapter
from lb_common.api import JsonlLogFormatter, attach_jsonl_handler, attach_loki_handler


class ControllerLogAttachmentService:
    """Attach structured logging handlers for the controller."""

    @staticmethod
    def attach_jsonl(context: RunContext, session: _RemoteSession) -> logging.Handler:
        _ = context
        controller_logger = logging.getLogger("lb_controller")
        controller_logger.setLevel(logging.INFO)
        return attach_jsonl_handler(
            controller_logger,
            output_dir=session.journal_path.parent,
            component="controller",
            host=platform.node() or "controller",
            run_id=session.effective_run_id,
            workload="controller",
            package="lb_controller",
            repetition=1,
        )

    @staticmethod
    def attach_loki(
        context: RunContext, session: _RemoteSession
    ) -> logging.Handler | None:
        loki_cfg = context.config.loki
        handler = attach_loki_handler(
            logging.getLogger(),
            enabled=loki_cfg.enabled,
            endpoint=loki_cfg.endpoint,
            component="controller",
            host=platform.node() or "controller",
            package="lb_controller",
            run_id=session.effective_run_id,
            workload="controller",
            repetition=1,
            labels=loki_cfg.labels,
            batch_size=loki_cfg.batch_size,
            flush_interval_ms=loki_cfg.flush_interval_ms,
            timeout_seconds=loki_cfg.timeout_seconds,
            max_retries=loki_cfg.max_retries,
            max_queue_size=loki_cfg.max_queue_size,
            backoff_base=loki_cfg.backoff_base,
            backoff_factor=loki_cfg.backoff_factor,
        )
        if handler:
            handler.setFormatter(
                JsonlLogFormatter(
                    component="controller",
                    host=platform.node() or "controller",
                    run_id=session.effective_run_id,
                    workload="controller",
                    package="lb_controller",
                    repetition=1,
                )
            )
        return handler


class RunExecutionCoordinator:
    """Coordinate remote execution via RemoteRunCoordinator."""

    def __init__(
        self,
        *,
        session_manager: SessionManager,
        execution_loop: RunExecutionLoop,
        progress_token: str,
        log_attachment_service: ControllerLogAttachmentService,
    ) -> None:
        self._session_manager = session_manager
        self._execution_loop = execution_loop
        self._progress_token = progress_token
        self._log_attachment_service = log_attachment_service
        self._remote = RemoteRunCoordinator(self)

    def run_remote(
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
        return self._remote.run(
            context,
            run_id,
            output_callback,
            formatter,
            ui_adapter,
            stop_token=stop_token,
            emit_timing=emit_timing,
        )

    def _prepare_remote_session(
        self,
        context: RunContext,
        run_id: str | None,
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None,
    ) -> _RemoteSession:
        return self._session_manager.prepare_remote_session(
            context, run_id, ui_adapter, stop_token
        )

    def _short_circuit_empty_run(
        self, context: RunContext, session: _RemoteSession, ui_adapter: UIAdapter | None
    ) -> RunResult:
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

        def event_from_payload(data: dict[str, str]) -> RunEvent | None:
            return event_from_payload_data(data, session, context)

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
    ):
        return self._execution_loop.run_loop(
            controller, context, session, pipeline, ui_adapter
        )

    def _attach_controller_jsonl(
        self, context: RunContext, session: _RemoteSession
    ) -> logging.Handler:
        return self._log_attachment_service.attach_jsonl(context, session)

    def _attach_controller_loki(
        self, context: RunContext, session: _RemoteSession
    ) -> logging.Handler | None:
        return self._log_attachment_service.attach_loki(context, session)

    def _parse_progress_line(self, line: str) -> dict[str, Any] | None:
        return parse_progress_line(line, token=self._progress_token)
