from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lb_plugins.plugins.dfaas.config import DfaasConfig, DfaasFunctionConfig
from lb_plugins.plugins.dfaas.services.run_execution import (
    DfaasConfigExecutor,
    DfaasResultWriter,
    DfaasRunContext,
)

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

    assert payload["dfaas_functions"] == ["a", "b"]
    assert payload["dfaas_results"] == [{"foo": "bar"}]


def test_config_executor_skip_reason_detects_indexed() -> None:
    ctx = _make_context(function_names=["f1"])
    key = (("f1",), (10,))
    ctx.existing_index.add(key)

    reason = DfaasConfigExecutor._check_skip_reason(ctx, [("f1", 10)], key)

    assert reason == "already_indexed"
