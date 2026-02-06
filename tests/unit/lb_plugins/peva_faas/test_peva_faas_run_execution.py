from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_plugins.plugins.peva_faas.config import DfaasConfig, DfaasFunctionConfig
from lb_plugins.plugins.peva_faas.services.run_execution import (
    DfaasConfigExecutor,
    DfaasResultWriter,
    DfaasRunContext,
)
from lb_plugins.plugins.peva_faas.services.plan_builder import config_key

pytestmark = [pytest.mark.unit_plugins]


def _make_context(function_names: list[str]) -> DfaasRunContext:
    return DfaasRunContext(
        function_names=function_names,
        configs=[],
        existing_index=set(),
        cooldown_manager=MagicMock(),
        base_idle=MagicMock(),
        target_name="node-1",
        run_id="run-1",
        output_dir=Path("/tmp"),
    )


def test_result_writer_falls_back_to_config_functions() -> None:
    config = DfaasConfig(
        functions=[
            DfaasFunctionConfig(name="b"),
            DfaasFunctionConfig(name="a"),
        ]
    )
    ctx = _make_context(function_names=[])
    ctx.results_rows = [{"foo": "bar"}]

    writer = DfaasResultWriter(config)
    payload = writer.build(ctx)

    assert payload["peva_faas_functions"] == ["a", "b"]
    assert payload["peva_faas_results"] == [{"foo": "bar"}]


def test_config_executor_skip_reason_detects_indexed() -> None:
    ctx = _make_context(function_names=["f1"])
    key = (("f1",), (10,))
    ctx.existing_index.add(key)

    reason = DfaasConfigExecutor._check_skip_reason(ctx, [("f1", 10)], key)

    assert reason == "already_indexed"


def _make_executor(scheduler: MagicMock | None = None) -> DfaasConfigExecutor:
    return DfaasConfigExecutor(
        config=DfaasConfig(functions=[DfaasFunctionConfig(name="f1")]),
        k6_runner=MagicMock(),
        metrics_collector=MagicMock(),
        result_builder=MagicMock(),
        annotations=MagicMock(),
        log_manager=MagicMock(),
        duration_seconds=30,
        outputs_provider=lambda: [],
        tags_provider=lambda _: {},
        replicas_provider=lambda _: {"f1": 1},
        scheduler=scheduler,
    )


def test_executor_requests_sequential_batch_from_scheduler() -> None:
    ctx = _make_context(function_names=["f1"])
    ctx.configs = [[("f1", 10)], [("f1", 20)]]
    scheduler = MagicMock()
    scheduler.propose_batch.return_value = [[("f1", 10)]]
    executed: list[list[tuple[str, int]]] = []
    executor = _make_executor(scheduler=scheduler)

    setattr(
        executor,
        "_execute_single_config",
        lambda *args: executed.append(args[1]),  # type: ignore[misc]
    )

    executor.execute(ctx)

    scheduler.propose_batch.assert_called_once_with(
        candidates=ctx.configs,
        seen_keys=ctx.existing_index,
        desired_size=2,
    )
    assert executed == [[("f1", 10)]]


def test_seen_config_is_skipped_without_replacement() -> None:
    ctx = _make_context(function_names=["f1"])
    ctx.configs = [[("f1", 10)], [("f1", 20)], [("f1", 30)]]
    ctx.existing_index.add(config_key([("f1", 20)]))
    executed: list[list[tuple[str, int]]] = []
    executor = _make_executor()

    setattr(
        executor,
        "_execute_single_config",
        lambda *args: executed.append(args[1]),  # type: ignore[misc]
    )

    executor.execute(ctx)

    assert executed == [[("f1", 10)], [("f1", 30)]]
