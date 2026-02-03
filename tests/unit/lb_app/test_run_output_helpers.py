"""Tests for run output helper modules."""

from __future__ import annotations

import pytest

from lb_app.services.run_output_formatting import (
    format_bullet_line,
    format_progress_line,
)
from lb_app.services.run_output_parsing import _extract_lb_task_data


pytestmark = pytest.mark.unit_ui


def test_format_bullet_line_normalizes_phase_and_host() -> None:
    rendered = format_bullet_line("Run: Phase", "hello", host_label="host-1")

    assert rendered == "• [run-phase] (host-1) hello"


def test_extract_lb_task_data_parses_payload() -> None:
    line = 'LB_TASK {"task": "do thing", "status": "ok", "duration_s": 1.5}'

    data = _extract_lb_task_data(line)

    assert data is not None
    assert data["task"] == "do thing"
    assert data["status"] == "ok"


def test_format_progress_line_renders_status_event() -> None:
    line = (
        'LB_EVENT {"host": "h1", "workload": "fio", "repetition": 1, '
        '"total_repetitions": 3, "status": "running"}'
    )

    rendered = format_progress_line(line)

    assert rendered == ("run fio", "1/3 running", "h1")


def test_format_progress_line_renders_log_event() -> None:
    line = (
        'LB_EVENT {"host": "h1", "workload": "fio", "repetition": 1, '
        '"total_repetitions": 3, "status": "running", '
        '"type": "log", "level": "ERROR", "message": "boom"}'
    )

    rendered = format_progress_line(line)

    assert rendered == ("run fio", "[ERROR] boom", "h1")
