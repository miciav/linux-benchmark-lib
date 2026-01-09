"""Tests for PlaybookProcessRunner stop/interrupt behavior."""

from __future__ import annotations

import os
import sys
import threading
import time

import pytest

from lb_controller.adapters.ansible_helpers import PlaybookProcessRunner
from lb_runner.api import StopToken


pytestmark = pytest.mark.unit_controller


def _sleep_cmd(seconds: float) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def test_playbook_process_runner_stop_token_stops(tmp_path) -> None:
    stop_token = StopToken(enable_signals=False)
    runner = PlaybookProcessRunner(
        private_data_dir=tmp_path,
        stream_output=True,
        output_callback=lambda _line, _end: None,
        stop_token=stop_token,
    )
    stop_token.request_stop()

    result = runner.run(_sleep_cmd(5), os.environ.copy(), cancellable=True)

    assert result.status == "stopped"


def test_playbook_process_runner_interrupt_stops(tmp_path) -> None:
    runner = PlaybookProcessRunner(
        private_data_dir=tmp_path,
        stream_output=True,
        output_callback=lambda _line, _end: None,
        stop_token=None,
    )
    result_holder: dict[str, object] = {}

    def _run() -> None:
        result_holder["result"] = runner.run(
            _sleep_cmd(5),
            os.environ.copy(),
            cancellable=True,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    for _ in range(50):
        if runner.is_running():
            break
        time.sleep(0.05)
    runner.interrupt()
    thread.join(timeout=5)

    result = result_holder.get("result")
    assert result is not None
    assert result.status == "stopped"
