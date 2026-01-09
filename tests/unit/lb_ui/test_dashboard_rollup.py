"""Tests for dashboard log rollup helper."""

from __future__ import annotations

import pytest

from lb_ui.tui.system.components.dashboard_rollup import PollingRollupHelper


pytestmark = pytest.mark.unit_ui


def test_polling_rollup_summarizes_polling_loop() -> None:
    log_buffer: list[str] = []
    helper = PollingRollupHelper(log_buffer, summary_only=True)

    assert helper.maybe_rollup("• [run dummy] (host1) Poll LB_EVENT stream done in 1.2s")
    assert helper.maybe_rollup("• [run dummy] (host1) Delay done in 0.8s")

    assert any("Polling loop poll x1 1.2s delay x1 0.8s" in line for line in log_buffer)


def test_polling_rollup_ignores_failed_tasks() -> None:
    log_buffer: list[str] = []
    helper = PollingRollupHelper(log_buffer, summary_only=True)

    assert helper.maybe_rollup("• [run dummy] Poll LB_EVENT stream failed") is False
    assert log_buffer == []
