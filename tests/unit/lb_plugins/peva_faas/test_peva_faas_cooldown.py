"""Unit tests for PEVA-faas CooldownManager service."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from lb_plugins.plugins.peva_faas.services.cooldown import (
    CooldownManager,
    CooldownResult,
    CooldownTimeoutError,
    MetricsSnapshot,
    within_threshold,
)

pytestmark = [pytest.mark.unit_plugins]


class TestMetricsSnapshot:
    def test_snapshot_is_frozen(self) -> None:
        snapshot = MetricsSnapshot(cpu=10.0, ram=1000.0, ram_pct=50.0, power=100.0)
        with pytest.raises(AttributeError):
            snapshot.cpu = 20.0  # type: ignore[misc]

    def test_snapshot_values(self) -> None:
        snapshot = MetricsSnapshot(cpu=10.0, ram=1000.0, ram_pct=50.0, power=100.0)
        assert snapshot.cpu == 10.0
        assert snapshot.ram == 1000.0
        assert snapshot.ram_pct == 50.0
        assert snapshot.power == 100.0


class TestWithinThreshold:
    def test_value_equal_to_baseline(self) -> None:
        assert within_threshold(100.0, 100.0, 0.1) is True

    def test_value_within_threshold(self) -> None:
        assert within_threshold(105.0, 100.0, 0.1) is True

    def test_value_at_threshold_boundary(self) -> None:
        assert within_threshold(110.0, 100.0, 0.1) is True

    def test_value_exceeds_threshold(self) -> None:
        assert within_threshold(111.0, 100.0, 0.1) is False

    def test_nan_baseline_returns_true(self) -> None:
        assert within_threshold(100.0, float("nan"), 0.1) is True

    def test_nan_value_returns_true(self) -> None:
        assert within_threshold(float("nan"), 100.0, 0.1) is True

    def test_both_nan_returns_true(self) -> None:
        assert within_threshold(float("nan"), float("nan"), 0.1) is True


class TestCooldownManager:
    def test_immediate_idle_returns_quickly(self) -> None:
        baseline = MetricsSnapshot(cpu=10.0, ram=1000.0, ram_pct=50.0, power=100.0)
        current = MetricsSnapshot(cpu=10.0, ram=1000.0, ram_pct=50.0, power=100.0)

        metrics_provider = MagicMock(return_value=current)
        replicas_provider = MagicMock(return_value={"func1": 1, "func2": 0})

        manager = CooldownManager(
            max_wait_seconds=60,
            sleep_step_seconds=5,
            idle_threshold_pct=10.0,
            metrics_provider=metrics_provider,
            replicas_provider=replicas_provider,
        )

        result = manager.wait_for_idle(baseline, ["func1", "func2"])

        assert isinstance(result, CooldownResult)
        assert result.waited_seconds == 0
        assert result.iterations == 1
        assert result.snapshot == current
        metrics_provider.assert_called_once()
        replicas_provider.assert_called_once_with(["func1", "func2"])

    def test_waits_until_metrics_settle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        baseline = MetricsSnapshot(cpu=10.0, ram=1000.0, ram_pct=50.0, power=100.0)
        high_cpu = MetricsSnapshot(cpu=50.0, ram=1000.0, ram_pct=50.0, power=100.0)
        normal = MetricsSnapshot(cpu=10.0, ram=1000.0, ram_pct=50.0, power=100.0)

        call_count = 0

        def metrics_provider() -> MetricsSnapshot:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return high_cpu
            return normal

        monkeypatch.setattr(
            "lb_plugins.plugins.peva_faas.services.cooldown.time.sleep", lambda _: None
        )

        manager = CooldownManager(
            max_wait_seconds=60,
            sleep_step_seconds=5,
            idle_threshold_pct=10.0,
            metrics_provider=metrics_provider,
            replicas_provider=lambda _: {"func1": 0},
        )

        result = manager.wait_for_idle(baseline, ["func1"])

        assert result.iterations == 3
        assert result.waited_seconds == 10  # 2 sleep cycles

    def test_waits_for_replicas_to_scale_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = MetricsSnapshot(cpu=10.0, ram=1000.0, ram_pct=50.0, power=100.0)

        replica_count = [5]  # Use list to allow mutation in closure

        def replicas_provider(names: list[str]) -> dict[str, int]:
            current = replica_count[0]
            if replica_count[0] > 1:
                replica_count[0] -= 1
            return {name: current for name in names}

        monkeypatch.setattr(
            "lb_plugins.plugins.peva_faas.services.cooldown.time.sleep", lambda _: None
        )

        manager = CooldownManager(
            max_wait_seconds=60,
            sleep_step_seconds=5,
            idle_threshold_pct=10.0,
            metrics_provider=lambda: baseline,
            replicas_provider=replicas_provider,
        )

        result = manager.wait_for_idle(baseline, ["func1"])

        assert result.waited_seconds > 0
        assert result.snapshot == baseline

    def test_timeout_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        baseline = MetricsSnapshot(cpu=10.0, ram=1000.0, ram_pct=50.0, power=100.0)
        high_cpu = MetricsSnapshot(cpu=50.0, ram=1000.0, ram_pct=50.0, power=100.0)

        monkeypatch.setattr(
            "lb_plugins.plugins.peva_faas.services.cooldown.time.sleep", lambda _: None
        )

        manager = CooldownManager(
            max_wait_seconds=10,
            sleep_step_seconds=5,
            idle_threshold_pct=10.0,
            metrics_provider=lambda: high_cpu,
            replicas_provider=lambda _: {"func1": 0},
        )

        with pytest.raises(CooldownTimeoutError) as exc_info:
            manager.wait_for_idle(baseline, ["func1"])

        assert exc_info.value.waited_seconds > 10
        assert exc_info.value.max_seconds == 10

    def test_nan_power_treated_as_idle(self) -> None:
        baseline = MetricsSnapshot(
            cpu=10.0, ram=1000.0, ram_pct=50.0, power=float("nan")
        )
        current = MetricsSnapshot(
            cpu=10.0, ram=1000.0, ram_pct=50.0, power=float("nan")
        )

        manager = CooldownManager(
            max_wait_seconds=60,
            sleep_step_seconds=5,
            idle_threshold_pct=10.0,
            metrics_provider=lambda: current,
            replicas_provider=lambda _: {"func1": 0},
        )

        result = manager.wait_for_idle(baseline, ["func1"])

        assert result.waited_seconds == 0

    def test_threshold_conversion_from_percentage(self) -> None:
        manager = CooldownManager(
            max_wait_seconds=60,
            sleep_step_seconds=5,
            idle_threshold_pct=20.0,  # 20%
            metrics_provider=lambda: MetricsSnapshot(0, 0, 0, 0),
            replicas_provider=lambda _: {},
        )
        assert manager.idle_threshold_pct == 0.2  # Converted to fraction

    def test_is_within_threshold_method(self) -> None:
        manager = CooldownManager(
            max_wait_seconds=60,
            sleep_step_seconds=5,
            idle_threshold_pct=10.0,
            metrics_provider=lambda: MetricsSnapshot(0, 0, 0, 0),
            replicas_provider=lambda _: {},
        )

        assert manager.is_within_threshold(100.0, 100.0) is True
        assert manager.is_within_threshold(110.0, 100.0) is True
        assert manager.is_within_threshold(111.0, 100.0) is False
        assert manager.is_within_threshold(float("nan"), 100.0) is True


class TestCooldownTimeoutError:
    def test_error_message(self) -> None:
        error = CooldownTimeoutError(waited_seconds=65, max_seconds=60)
        assert "65s" in str(error)
        assert "60s" in str(error)
        assert error.waited_seconds == 65
        assert error.max_seconds == 60

    def test_is_timeout_error(self) -> None:
        error = CooldownTimeoutError(waited_seconds=10, max_seconds=5)
        assert isinstance(error, TimeoutError)
