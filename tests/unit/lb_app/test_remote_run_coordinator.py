"""Tests for RemoteRunCoordinator flow decisions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lb_app.services.remote_run_coordinator import RemoteRunCoordinator
import lb_app.services.remote_run_coordinator as coordinator_mod
from lb_app.services.run_types import RunContext, RunResult, _EventPipeline
from lb_controller.api import BenchmarkConfig, RemoteHostConfig, StopToken


pytestmark = pytest.mark.unit_ui


class _DummyService:
    def __init__(self, session, short_result, pipeline, summary) -> None:
        self._session = session
        self.short_result = short_result
        self.pipeline = pipeline
        self.summary = summary
        self.short_circuit_called = False
        self.pipeline_called = False
        self.run_called = False

    def _prepare_remote_session(self, *_args, **_kwargs):
        return self._session

    def _attach_controller_jsonl(self, *_args, **_kwargs):
        return None

    def _attach_controller_loki(self, *_args, **_kwargs):
        return None

    def _short_circuit_empty_run(self, *_args, **_kwargs):
        self.short_circuit_called = True
        return self.short_result

    def _build_event_pipeline(self, *_args, **_kwargs):
        self.pipeline_called = True
        return self.pipeline

    def _run_controller_loop(self, *_args, **_kwargs):
        self.run_called = True
        return self.summary


class _FailingService(_DummyService):
    def __init__(self, session, pipeline) -> None:
        super().__init__(
            session,
            short_result=RunResult(context=_make_context(), summary=None),
            pipeline=pipeline,
            summary=None,
        )

    def _run_controller_loop(self, *_args, **_kwargs):
        self.run_called = True
        raise RuntimeError("boom")


def _make_context() -> RunContext:
    cfg = BenchmarkConfig()
    cfg.remote_hosts = [RemoteHostConfig(name="host", address="127.0.0.1", user="root")]
    cfg.repetitions = 1
    return RunContext(
        config=cfg, target_tests=["stress_ng"], registry=SimpleNamespace()
    )


def _make_session(stop_token: StopToken):
    return SimpleNamespace(
        stop_token=stop_token,
        journal=object(),
        resume_requested=False,
        dashboard=SimpleNamespace(refresh=lambda: None),
        controller_state=SimpleNamespace(),
        journal_path=SimpleNamespace(parent=SimpleNamespace()),
        log_path=SimpleNamespace(),
        ui_stream_log_path=None,
        sink=SimpleNamespace(close=lambda: None),
        log_file=SimpleNamespace(
            write=lambda *_: None, flush=lambda: None, close=lambda: None
        ),
        ui_stream_log_file=None,
        effective_run_id="run-1",
    )


def _make_pipeline() -> _EventPipeline:
    return _EventPipeline(
        output_cb=lambda *_: None,
        announce_stop=lambda *_: None,
        ingest_event=lambda *_: None,
        event_from_payload=lambda *_: None,
        sink=SimpleNamespace(close=lambda: None),
        controller_ref={"controller": None},
    )


def test_remote_run_short_circuits_when_no_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_token = StopToken(enable_signals=False)
    session = _make_session(stop_token)
    short_result = RunResult(context=_make_context(), summary=None)
    service = _DummyService(session, short_result, _make_pipeline(), summary=None)
    coordinator = RemoteRunCoordinator(service)

    monkeypatch.setattr(
        coordinator_mod, "pending_exists", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(coordinator_mod, "apply_playbook_defaults", lambda *_: None)
    monkeypatch.setattr(
        coordinator_mod, "apply_plugin_assets", lambda *_args, **_kwargs: None
    )

    result = coordinator.run(
        _make_context(),
        run_id="run-1",
        output_callback=lambda *_: None,
        formatter=None,
        ui_adapter=None,
        stop_token=stop_token,
        emit_timing=False,
    )

    assert service.short_circuit_called is True
    assert service.pipeline_called is False
    assert service.run_called is False
    assert result is short_result


def test_remote_run_short_circuit_cleans_up_session_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _StopToken:
        def __init__(self) -> None:
            self._on_stop = None

        def should_stop(self) -> bool:
            return False

        def restore(self) -> None:
            events.append("restore")

    session = _make_session(_StopToken())
    session.sink = SimpleNamespace(close=lambda: events.append("sink_close"))
    session.log_file = SimpleNamespace(
        write=lambda *_: None,
        flush=lambda: None,
        close=lambda: events.append("log_close"),
    )
    session.ui_stream_log_file = SimpleNamespace(
        close=lambda: events.append("ui_close")
    )
    short_result = RunResult(context=_make_context(), summary=None)
    service = _DummyService(session, short_result, _make_pipeline(), summary=None)
    coordinator = RemoteRunCoordinator(service)

    monkeypatch.setattr(
        coordinator_mod, "pending_exists", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(coordinator_mod, "apply_playbook_defaults", lambda *_: None)
    monkeypatch.setattr(
        coordinator_mod, "apply_plugin_assets", lambda *_args, **_kwargs: None
    )

    result = coordinator.run(
        _make_context(),
        run_id="run-1",
        output_callback=lambda *_: None,
        formatter=None,
        ui_adapter=None,
        stop_token=session.stop_token,
        emit_timing=False,
    )

    assert service.short_circuit_called is True
    assert service.pipeline_called is False
    assert service.run_called is False
    assert result is short_result
    assert "sink_close" in events
    assert "restore" in events
    assert "log_close" in events
    assert "ui_close" in events


def test_remote_run_executes_when_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    stop_token = StopToken(enable_signals=False)
    session = _make_session(stop_token)
    summary = object()
    service = _DummyService(
        session,
        RunResult(context=_make_context(), summary=None),
        _make_pipeline(),
        summary=summary,
    )
    coordinator = RemoteRunCoordinator(service)

    monkeypatch.setattr(coordinator_mod, "pending_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(coordinator_mod, "apply_playbook_defaults", lambda *_: None)
    monkeypatch.setattr(
        coordinator_mod, "apply_plugin_assets", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        coordinator_mod, "maybe_start_event_tailer", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        coordinator_mod, "BenchmarkController", lambda *_args, **_kwargs: object()
    )

    result = coordinator.run(
        _make_context(),
        run_id="run-1",
        output_callback=lambda *_: None,
        formatter=None,
        ui_adapter=None,
        stop_token=stop_token,
        emit_timing=False,
    )

    assert service.short_circuit_called is False
    assert service.pipeline_called is True
    assert service.run_called is True
    assert result.summary is summary


def test_remote_run_cleans_up_when_controller_loop_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_events: list[str] = []

    class _StopToken:
        def __init__(self) -> None:
            self._on_stop = None

        def should_stop(self) -> bool:
            return False

        def restore(self) -> None:
            stop_events.append("restore")

    session = _make_session(_StopToken())
    session.sink = SimpleNamespace(close=lambda: stop_events.append("sink_close"))
    tailer = SimpleNamespace(stop=lambda: stop_events.append("tailer_stop"))
    service = _FailingService(session, _make_pipeline())
    coordinator = RemoteRunCoordinator(service)

    monkeypatch.setattr(coordinator_mod, "pending_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(coordinator_mod, "apply_playbook_defaults", lambda *_: None)
    monkeypatch.setattr(
        coordinator_mod, "apply_plugin_assets", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        coordinator_mod, "maybe_start_event_tailer", lambda *_args, **_kwargs: tailer
    )
    monkeypatch.setattr(
        coordinator_mod, "BenchmarkController", lambda *_args, **_kwargs: object()
    )

    with pytest.raises(RuntimeError, match="boom"):
        coordinator.run(
            _make_context(),
            run_id="run-1",
            output_callback=lambda *_: None,
            formatter=None,
            ui_adapter=None,
            stop_token=session.stop_token,
            emit_timing=False,
        )

    assert "tailer_stop" in stop_events
    assert "sink_close" in stop_events
    assert "restore" in stop_events
