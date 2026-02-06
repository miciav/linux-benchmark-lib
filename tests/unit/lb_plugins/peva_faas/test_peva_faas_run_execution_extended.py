from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import lb_plugins.plugins.peva_faas.services.run_execution as run_execution_mod
from lb_plugins.plugins.peva_faas.config import DfaasConfig, DfaasFunctionConfig
from lb_plugins.plugins.peva_faas.exceptions import K6ExecutionError
from lb_plugins.plugins.peva_faas.services.cooldown import (
    CooldownResult,
    CooldownTimeoutError,
    MetricsSnapshot,
)
from lb_plugins.plugins.peva_faas.services.plan_builder import config_id, config_key
from lb_plugins.plugins.peva_faas.services.run_execution import (
    DfaasConfigExecutor,
    DfaasRunContext,
)

pytestmark = [pytest.mark.unit_plugins]


def _make_context(
    *,
    function_names: list[str] | None = None,
    configs: list[list[tuple[str, int]]] | None = None,
) -> DfaasRunContext:
    return DfaasRunContext(
        function_names=function_names or ["f1"],
        configs=configs or [],
        existing_index=set(),
        cooldown_manager=MagicMock(),
        base_idle=MetricsSnapshot(cpu=1.0, ram=2.0, ram_pct=3.0, power=4.0),
        target_name="target-node",
        run_id="run-1",
        output_dir=Path("/tmp/peva"),
        repetition=5,
    )


def _make_executor(
    *,
    config: DfaasConfig | None = None,
    memory_engine: MagicMock | None = None,
) -> tuple[DfaasConfigExecutor, dict[str, MagicMock]]:
    cfg = config or DfaasConfig(functions=[DfaasFunctionConfig(name="f1")], iterations=3)
    deps = {
        "k6_runner": MagicMock(),
        "metrics_collector": MagicMock(),
        "result_builder": MagicMock(),
        "annotations": MagicMock(),
        "log_manager": MagicMock(),
        "scheduler": MagicMock(),
    }
    deps["scheduler"].propose_batch.side_effect = (
        lambda candidates, **_kwargs: candidates
    )
    executor = DfaasConfigExecutor(
        config=cfg,
        k6_runner=deps["k6_runner"],
        metrics_collector=deps["metrics_collector"],
        result_builder=deps["result_builder"],
        annotations=deps["annotations"],
        log_manager=deps["log_manager"],
        duration_seconds=30,
        outputs_provider=lambda: ["loki=http://localhost"],
        tags_provider=lambda run_id: {"run_id": run_id},
        replicas_provider=lambda names: {name: 1 for name in names},
        scheduler=deps["scheduler"],
        memory_engine=memory_engine,
    )
    return executor, deps


def test_check_skip_reason_detects_dominated_configs() -> None:
    ctx = _make_context()
    ctx.overloaded_configs = [[("f1", 10)]]

    reason = DfaasConfigExecutor._check_skip_reason(
        ctx,
        config_pairs=[("f1", 20)],
        key=config_key([("f1", 20)]),
    )

    assert reason == "dominated_by_overload"


def test_execute_single_config_skips_when_reason_is_present() -> None:
    executor, deps = _make_executor()
    ctx = _make_context()
    pairs = [("f1", 10)]
    ctx.existing_index.add(config_key(pairs))
    deps["result_builder"].build_skipped_row.return_value = {"skipped": True}

    executor._execute_single_config(
        ctx=ctx,
        config_pairs=pairs,
        idx=1,
        total_configs=1,
        total_iterations=2,
    )

    deps["k6_runner"].build_script.assert_not_called()
    deps["annotations"].annotate_config_change.assert_not_called()
    assert ctx.skipped_rows == [{"skipped": True}]


def test_execute_single_config_appends_overloaded_and_index_rows() -> None:
    config = DfaasConfig(functions=[DfaasFunctionConfig(name="f1")], iterations=3)
    executor, deps = _make_executor(config=config)
    ctx = _make_context()
    deps["k6_runner"].build_script.return_value = ("script", {"f1": "metric-id"})
    executor._run_config_iterations = lambda *args, **kwargs: 2  # type: ignore[method-assign]

    executor._execute_single_config(
        ctx=ctx,
        config_pairs=[("f1", 10)],
        idx=1,
        total_configs=1,
        total_iterations=3,
    )

    cfg_id = config_id([("f1", 10)])
    assert ctx.script_entries == [{"config_id": cfg_id, "script": "script"}]
    assert ctx.overloaded_configs == [[("f1", 10)]]
    assert ctx.index_rows == [
        {"functions": ["f1"], "rates": [10], "results_file": "results.csv"}
    ]


def test_execute_single_config_stops_when_iteration_runner_returns_none() -> None:
    executor, deps = _make_executor()
    ctx = _make_context()
    deps["k6_runner"].build_script.return_value = ("script", {"f1": "metric-id"})
    executor._run_config_iterations = lambda *args, **kwargs: None  # type: ignore[method-assign]

    executor._execute_single_config(
        ctx=ctx,
        config_pairs=[("f1", 10)],
        idx=1,
        total_configs=1,
        total_iterations=1,
    )

    cfg_id = config_id([("f1", 10)])
    assert ctx.script_entries == [{"config_id": cfg_id, "script": "script"}]
    assert ctx.index_rows == []


def test_execute_iteration_appends_entries_and_ingests_memory_event() -> None:
    memory_engine = MagicMock()
    executor, deps = _make_executor(memory_engine=memory_engine)
    ctx = _make_context(function_names=["f1"])
    deps["result_builder"].build_result_row.return_value = ({"row": "ok"}, True)

    executor._emit_iteration_message = MagicMock()  # type: ignore[method-assign]
    executor._perform_cooldown = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        MetricsSnapshot(cpu=1.0, ram=2.0, ram_pct=3.0, power=4.0),
        4,
    )
    executor._run_k6_iteration = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        SimpleNamespace(summary={"metrics": {}}, duration_seconds=1.0),
        10.0,
        12.0,
    )
    executor._parse_summary_or_raise = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        "f1": {"success_rate": 1.0}
    }
    executor._collect_metrics = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        "cpu_usage_node": 9.0
    }

    overloaded = executor._execute_iteration(
        ctx=ctx,
        config_pairs=[("f1", 10)],
        script="script",
        metric_ids={"f1": "id-1"},
        cfg_id="f1-10",
        pairs_label="f1=10",
        idx=1,
        total_configs=2,
        iteration=1,
        total_iterations=2,
    )

    assert overloaded is True
    deps["annotations"].annotate_overload.assert_called_once()
    assert len(ctx.results_rows) == 1
    assert len(ctx.metrics_entries) == 1
    assert len(ctx.summary_entries) == 1
    memory_engine.ingest_event.assert_called_once()
    event = memory_engine.ingest_event.call_args.args[0]
    assert event.config_id == "f1-10"
    assert event.repetition == 5


def test_ingest_memory_event_logs_warning_on_memory_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    memory_engine = MagicMock()
    memory_engine.ingest_event.side_effect = RuntimeError("boom")
    executor, _deps = _make_executor(memory_engine=memory_engine)
    ctx = _make_context()
    caplog.set_level("WARNING")

    executor._ingest_memory_event(
        ctx=ctx,
        config_pairs=[("f1", 10)],
        cfg_id="f1-10",
        iteration=1,
        start_time=10.0,
        end_time=12.0,
        row={"row": "ok"},
        metrics={"cpu_usage_node": 1.0},
        summary_data={"metrics": {}},
    )

    assert "Memory ingest failed for f1-10" in caplog.text


def test_parse_summary_or_raise_wraps_value_error() -> None:
    executor, deps = _make_executor()
    deps["k6_runner"].parse_summary.side_effect = ValueError("missing")

    with pytest.raises(K6ExecutionError, match="missing k6 summary metrics: missing"):
        executor._parse_summary_or_raise(
            summary_data={"metrics": {}},
            metric_ids={"f1": "id-1"},
            cfg_id="f1-10",
        )


def test_run_config_iterations_counts_overloads() -> None:
    executor, _deps = _make_executor()
    ctx = _make_context()
    overloads = iter([True, False, True])
    executor._execute_iteration = lambda *args, **kwargs: next(overloads)  # type: ignore[method-assign]

    counter = executor._run_config_iterations(
        ctx=ctx,
        config_pairs=[("f1", 10)],
        script="script",
        metric_ids={"f1": "id-1"},
        cfg_id="f1-10",
        pairs_label="f1=10",
        idx=1,
        total_configs=1,
        total_iterations=3,
    )

    assert counter == 2


def test_run_config_iterations_handles_cooldown_timeout() -> None:
    executor, _deps = _make_executor()
    ctx = _make_context()
    executor._execute_iteration = MagicMock(  # type: ignore[method-assign]
        side_effect=CooldownTimeoutError(waited_seconds=8, max_seconds=5)
    )
    executor._handle_cooldown_timeout = MagicMock()  # type: ignore[method-assign]

    result = executor._run_config_iterations(
        ctx=ctx,
        config_pairs=[("f1", 10)],
        script="script",
        metric_ids={"f1": "id-1"},
        cfg_id="f1-10",
        pairs_label="f1=10",
        idx=1,
        total_configs=1,
        total_iterations=1,
    )

    assert result is None
    executor._handle_cooldown_timeout.assert_called_once()


@pytest.mark.parametrize(
    ("exc", "handler_name"),
    [
        (K6ExecutionError("f1-10", "boom"), "_handle_k6_error"),
        (RuntimeError("boom"), "_handle_execution_error"),
        (OSError("io"), "_handle_execution_error"),
        (json.JSONDecodeError("bad", "{}", 0), "_handle_execution_error"),
    ],
)
def test_run_config_iterations_handles_execution_exceptions(
    exc: Exception, handler_name: str
) -> None:
    executor, _deps = _make_executor()
    ctx = _make_context()
    executor._execute_iteration = MagicMock(side_effect=exc)  # type: ignore[method-assign]
    executor._handle_k6_error = MagicMock()  # type: ignore[method-assign]
    executor._handle_execution_error = MagicMock()  # type: ignore[method-assign]

    result = executor._run_config_iterations(
        ctx=ctx,
        config_pairs=[("f1", 10)],
        script="script",
        metric_ids={"f1": "id-1"},
        cfg_id="f1-10",
        pairs_label="f1=10",
        idx=1,
        total_configs=1,
        total_iterations=1,
    )

    assert result is None
    getattr(executor, handler_name).assert_called_once()


def test_perform_cooldown_and_run_k6_iteration_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, deps = _make_executor()
    ctx = _make_context(function_names=["f1", "f2"])
    snapshot = MetricsSnapshot(cpu=5.0, ram=6.0, ram_pct=7.0, power=8.0)
    ctx.cooldown_manager.wait_for_idle.return_value = CooldownResult(
        snapshot=snapshot,
        waited_seconds=6,
        iterations=2,
    )
    deps["k6_runner"].execute.return_value = SimpleNamespace(duration_seconds=2.5)
    times = iter([100.0, 105.0])
    monkeypatch.setattr(run_execution_mod.time, "time", lambda: next(times))

    idle_snapshot, rest_seconds = executor._perform_cooldown(ctx, "f1-10")
    result, start_time, end_time = executor._run_k6_iteration(
        ctx, "f1-10", "script", {"f1": "id-1"}
    )

    assert idle_snapshot == snapshot
    assert rest_seconds == 6
    assert result.duration_seconds == 2.5
    assert start_time == 100.0
    assert end_time == 105.0
    deps["k6_runner"].execute.assert_called_once_with(
        "f1-10",
        "script",
        "target-node",
        "run-1",
        {"f1": "id-1"},
        output_dir=Path("/tmp/peva"),
        outputs=["loki=http://localhost"],
        tags={"run_id": "run-1"},
    )


def test_handle_error_helpers_append_skipped_rows() -> None:
    executor, deps = _make_executor()
    ctx = _make_context()
    deps["result_builder"].build_skipped_row.return_value = {"skipped": True}

    executor._handle_cooldown_timeout(
        ctx=ctx,
        config_pairs=[("f1", 10)],
        cfg_id="f1-10",
        exc=CooldownTimeoutError(waited_seconds=5, max_seconds=4),
    )
    executor._handle_k6_error(
        ctx=ctx,
        config_pairs=[("f1", 20)],
        cfg_id="f1-20",
        exc=K6ExecutionError("f1-20", "failed", stderr="stderr line"),
    )
    executor._handle_execution_error(
        ctx=ctx,
        config_pairs=[("f1", 30)],
        cfg_id="f1-30",
        exc=RuntimeError("boom"),
    )

    assert len(ctx.skipped_rows) == 3
    assert deps["annotations"].annotate_error.call_count == 3


def test_format_pairs_label_sorts_by_function_name() -> None:
    assert DfaasConfigExecutor._format_pairs_label([("b", 20), ("a", 10)]) == "a=10, b=20"
