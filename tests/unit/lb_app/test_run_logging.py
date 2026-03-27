"""Tests for run logging helpers."""

from __future__ import annotations

from io import StringIO

import pytest

from lb_app.services.run_logging import emit_warning


pytestmark = pytest.mark.unit_ui


class _RecordingUIAdapter:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def show_warning(self, message: str) -> None:
        self.warnings.append(message)

    def show_info(self, message: str) -> None:
        raise AssertionError(f"unexpected info: {message}")


class _RecordingDashboard:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, float]] = []
        self.logs: list[str] = []
        self.refresh_calls = 0

    def add_log(self, line: str) -> None:
        self.logs.append(line)

    def refresh(self) -> None:
        self.refresh_calls += 1

    def mark_event(self, source: str) -> None:
        _ = source

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        self.warnings.append((message, ttl))


def test_emit_warning_reaches_dashboard_banner_even_with_ui_adapter() -> None:
    ui_adapter = _RecordingUIAdapter()
    dashboard = _RecordingDashboard()
    log_file = StringIO()

    emit_warning(
        "Press Ctrl+C again within 10s to force stop.",
        dashboard=dashboard,
        ui_adapter=ui_adapter,
        log_file=log_file,
        ui_stream_log_file=None,
        ttl=10.0,
    )

    assert ui_adapter.warnings == ["Press Ctrl+C again within 10s to force stop."]
    assert dashboard.warnings == [
        ("Press Ctrl+C again within 10s to force stop.", 10.0)
    ]
    assert dashboard.logs == []
    assert dashboard.refresh_calls == 1
    assert log_file.getvalue() == "Press Ctrl+C again within 10s to force stop.\n"
