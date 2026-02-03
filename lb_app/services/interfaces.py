"""Internal interfaces for service coordination."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Protocol, IO

if TYPE_CHECKING:
    from logging import Handler
    from lb_app.services.run_types import RunContext, _RemoteSession, _EventPipeline
    from lb_app.services.run_output import AnsibleOutputFormatter
    from lb_app.ui_interfaces import UIAdapter
    from lb_controller.api import StopToken
    from lb_app.services.run_types import RunResult


class IRunService(Protocol):
    """Protocol defining the subset of RunService used by Coordinators."""

    def _prepare_remote_session(
        self,
        context: RunContext,
        run_id: str | None,
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None,
    ) -> _RemoteSession: ...

    def _short_circuit_empty_run(
        self,
        context: RunContext,
        session: _RemoteSession,
        ui_adapter: UIAdapter | None,
    ) -> RunResult: ...

    def _build_event_pipeline(
        self,
        context: RunContext,
        session: _RemoteSession,
        formatter: AnsibleOutputFormatter | None,
        output_callback: Callable[[str, str], None],
        ui_adapter: UIAdapter | None,
        emit_timing: bool,
    ) -> _EventPipeline: ...

    def _attach_controller_jsonl(
        self, context: RunContext, session: _RemoteSession
    ) -> Handler: ...

    def _attach_controller_loki(
        self, context: RunContext, session: _RemoteSession
    ) -> Handler | None: ...
