"""Tests for BaseCollector failure backoff and error history policy."""

from __future__ import annotations

import time

from tests.unit.lb_runner.engine_tests.test_base_collector import DummyCollector


def test_failing_collector_sleeps_between_failures(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    collector = DummyCollector(interval_seconds=0.5, raise_on_collect=True)
    collector._is_running = True

    def fake_sleep(value: float) -> None:
        sleeps.append(value)
        collector._is_running = False

    monkeypatch.setattr(time, "sleep", fake_sleep)

    collector._collection_loop()

    assert sleeps
    assert sleeps[0] >= 0.5


def test_failing_collector_caps_error_history(monkeypatch) -> None:
    sleeps: list[float] = []
    collector = DummyCollector(interval_seconds=0.01, raise_on_collect=True)
    collector.max_error_records = 3
    collector._is_running = True

    def fake_sleep(value: float) -> None:
        sleeps.append(value)
        if len(sleeps) >= 5:
            collector._is_running = False

    monkeypatch.setattr(time, "sleep", fake_sleep)

    collector._collection_loop()

    assert len(collector.get_errors()) == 3
