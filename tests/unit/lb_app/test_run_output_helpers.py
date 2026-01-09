"""Tests for run output helper modules."""

from __future__ import annotations

import pytest

from lb_app.services.run_output_formatting import format_bullet_line
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
