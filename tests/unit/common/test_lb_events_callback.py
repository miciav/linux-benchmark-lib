import json
import os
from pathlib import Path

from lb_controller.ansible.callback_plugins.lb_events import (
    CallbackModule,
    _extract_lb_event,
)

import pytest

pytestmark = pytest.mark.unit

class _Host:
    def __init__(self, name: str):
        self._name = name

    def get_name(self) -> str:
        return self._name


class _Result:
    def __init__(self, host: str, msg: str):
        self._host = _Host(host)
        self._result = {"msg": msg}


def test_extract_lb_event_handles_escaped_payload():
    text = (
        'ok: [lb-worker] => {"msg": "LB_EVENT '
        '{\\"host\\": \\"lb-worker\\", \\"workload\\": \\"fio\\", \\"repetition\\": 2, '
        '\\"total_repetitions\\": 3, \\"status\\": \\"running\\"}"}'
    )
    data = _extract_lb_event(text)
    assert data == {
        "host": "lb-worker",
        "workload": "fio",
        "repetition": 2,
        "total_repetitions": 3,
        "status": "running",
    }


def test_callback_writes_event(tmp_path: Path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("LB_EVENT_LOG_PATH", str(log_path))

    cb = CallbackModule()
    res = _Result(
        "h1",
        'LB_EVENT {"host": "h1", "workload": "fio", "repetition": 1, "total_repetitions": 3, "status": "done"}',
    )

    cb.v2_runner_on_ok(res)

    contents = log_path.read_text().strip().splitlines()
    assert len(contents) == 1
    payload = json.loads(contents[0])
    assert payload["host"] == "h1"
    assert payload["status"] == "done"
    assert payload["workload"] == "fio"
