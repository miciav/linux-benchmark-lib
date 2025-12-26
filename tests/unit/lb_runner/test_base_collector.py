"""Tests for BaseCollector lifecycle and error handling."""

import time

import pytest

from lb_runner.api import BaseCollector

import pytest

pytestmark = pytest.mark.unit_runner

class DummyCollector(BaseCollector):
    def __init__(self, interval_seconds: float = 0.01, fail_env: bool = False, raise_on_collect: bool = False):
        super().__init__("Dummy", interval_seconds=interval_seconds)
        self.fail_env = fail_env
        self.raise_on_collect = raise_on_collect

    def _collect_metrics(self):
        if self.raise_on_collect:
            raise RuntimeError("boom")
        return {"value": 1}

    def _validate_environment(self) -> bool:
        return not self.fail_env

    def _stop_workload(self) -> None:
        self._is_running = False


def test_start_raises_when_env_invalid():
    c = DummyCollector(fail_env=True)
    with pytest.raises(RuntimeError):
        c.start()


def test_collect_loop_stores_data_and_stops_cleanly():
    c = DummyCollector()
    c.start()
    time.sleep(0.05)
    c.stop()
    data = c.get_data()
    assert data, "Collector should have collected at least one datapoint"
    # ensure timestamp/collector keys present
    assert all("timestamp" in entry and entry["collector"] == "Dummy" for entry in data)


def test_collect_loop_survives_exceptions():
    c = DummyCollector(raise_on_collect=True)
    c.start()
    time.sleep(0.05)
    c.stop()
    # No exception should propagate; data may be empty due to raised collects
    assert c._is_running is False
