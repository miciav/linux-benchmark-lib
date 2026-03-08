from __future__ import annotations

import importlib
from pathlib import Path

import lb_app.services.run_events as run_events


def _reload_run_events() -> object:
    return importlib.reload(run_events)


def test_json_event_tailer_debug_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LB_EVENT_DEBUG", raising=False)
    module = _reload_run_events()
    log_path = tmp_path / "events.jsonl"

    tailer = module.JsonEventTailer(log_path, lambda _event: None, poll_interval=0.01)
    tailer.start()
    tailer.stop()

    assert module._DEBUG is False
    assert not (tmp_path / "lb_events.tailer.debug.log").exists()


def test_json_event_tailer_writes_debug_log_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LB_EVENT_DEBUG", "1")
    module = _reload_run_events()
    log_path = tmp_path / "events.jsonl"

    tailer = module.JsonEventTailer(log_path, lambda _event: None, poll_interval=0.01)
    tailer.start()
    tailer.stop()

    debug_path = tmp_path / "lb_events.tailer.debug.log"
    assert module._DEBUG is True
    assert debug_path.exists()
    assert "Tailer started" in debug_path.read_text()
