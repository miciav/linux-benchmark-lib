from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_plugins.plugins.dfaas.config import DfaasConfig, DfaasFunctionConfig
from lb_plugins.plugins.dfaas.services.annotation_service import (
    DfaasAnnotationService,
)
from lb_plugins.plugins.dfaas.services.log_manager import DfaasLogManager
from lb_plugins.plugins.dfaas.services.run_execution import (
    DfaasConfigExecutor,
    DfaasResultWriter,
    DfaasRunContext,
    DfaasRunPlanner,
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


def _make_planner(config: DfaasConfig) -> DfaasRunPlanner:
    return DfaasRunPlanner(
        config=config,
        exec_ctx=MagicMock(host="node-1"),
        planner=MagicMock(),
        metrics_collector=MagicMock(),
        log_manager=MagicMock(spec=DfaasLogManager),
        annotations=MagicMock(spec=DfaasAnnotationService),
        replicas_provider=lambda names: {name: 0 for name in names},
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


def test_result_writer_keeps_success_for_skip_only_runs() -> None:
    config = DfaasConfig(functions=[DfaasFunctionConfig(name="figlet")])
    ctx = _make_context(function_names=["figlet"])
    ctx.skipped_rows = [{"function_figlet": "figlet", "rate_function_figlet": 10}]
    ctx.results_rows = []
    ctx.index_rows = []
    ctx.summary_entries = []
    ctx.metrics_entries = []
    ctx.script_entries = []

    writer = DfaasResultWriter(config)
    payload = writer.build(ctx)

    assert payload["success"] is True
    assert payload["returncode"] == 0


def test_result_writer_marks_failure_for_execution_errors() -> None:
    config = DfaasConfig(functions=[DfaasFunctionConfig(name="figlet")])
    ctx = _make_context(function_names=["figlet"])
    ctx.failed_configs = 1

    writer = DfaasResultWriter(config)
    payload = writer.build(ctx)

    assert payload["success"] is False
    assert payload["returncode"] != 0


def test_config_executor_skip_reason_detects_indexed() -> None:
    ctx = _make_context(function_names=["f1"])
    key = (("f1",), (10,))
    ctx.existing_index.add(key)

    reason = DfaasConfigExecutor._check_skip_reason(ctx, [("f1", 10)], key)

    assert reason == "already_indexed"


def test_handle_execution_error_marks_failure_and_skips_row() -> None:
    config = DfaasConfig(functions=[DfaasFunctionConfig(name="figlet")])
    result_builder = MagicMock()
    result_builder.build_skipped_row.return_value = {"skipped": True}
    annotations = MagicMock(spec=DfaasAnnotationService)
    executor = DfaasConfigExecutor(
        config=config,
        k6_runner=MagicMock(),
        metrics_collector=MagicMock(),
        result_builder=result_builder,
        annotations=annotations,
        log_manager=MagicMock(spec=DfaasLogManager),
        duration_seconds=30,
        outputs_provider=lambda: [],
        tags_provider=lambda run_id: {"run_id": run_id},
        replicas_provider=lambda names: {name: 0 for name in names},
    )
    ctx = _make_context(function_names=["figlet"])

    executor._handle_execution_error(
        ctx,
        [("figlet", 10)],
        "cfg-1",
        RuntimeError("boom"),
    )

    assert ctx.failed_configs == 1
    assert ctx.skipped_rows == [{"skipped": True}]
    annotations.annotate_error.assert_called_once()


def test_execute_public_path_marks_final_payload_failed() -> None:
    config = DfaasConfig(
        functions=[DfaasFunctionConfig(name="figlet")],
        iterations=1,
    )
    result_builder = MagicMock()
    result_builder.build_skipped_row.return_value = {"skipped": True}
    annotations = MagicMock(spec=DfaasAnnotationService)
    executor = DfaasConfigExecutor(
        config=config,
        k6_runner=MagicMock(),
        metrics_collector=MagicMock(),
        result_builder=result_builder,
        annotations=annotations,
        log_manager=MagicMock(spec=DfaasLogManager),
        duration_seconds=30,
        outputs_provider=lambda: [],
        tags_provider=lambda run_id: {"run_id": run_id},
        replicas_provider=lambda names: {name: 0 for name in names},
    )
    ctx = _make_context(function_names=["figlet"])
    ctx.configs = [[("figlet", 10)]]
    executor._k6_runner.build_script.return_value = ("script", {"figlet": "fn_1"})
    executor._perform_cooldown = MagicMock(return_value=(MagicMock(), 0))  # type: ignore[method-assign]
    executor._run_k6_iteration = MagicMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("boom")
    )

    executor.execute(ctx)
    payload = DfaasResultWriter(config).build(ctx)

    assert payload["success"] is False
    assert payload["returncode"] != 0


def test_resolve_run_id_uses_parent_for_host_scoped_output_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated_config = tmp_path / "benchmark_config.generated.json"
    generated_config.write_text(
        json.dumps(
            {
                "output_dir": str(
                    tmp_path / "benchmark_results" / "run-2026-03-23" / "node-1"
                ),
                "workloads": {"dfaas": {"plugin": "dfaas"}},
            }
        )
    )
    monkeypatch.chdir(tmp_path)

    config = DfaasConfig(functions=[DfaasFunctionConfig(name="figlet")])
    planner = _make_planner(config)

    run_id = planner._resolve_run_id()

    assert run_id == "run-2026-03-23"


def test_resolve_run_id_uses_output_dir_name_for_local_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated_config = tmp_path / "benchmark_config.generated.json"
    generated_config.write_text(
        json.dumps(
            {
                "output_dir": str(tmp_path / "reports" / "run-2026-03-23"),
                "workloads": {"dfaas": {"plugin": "dfaas"}},
            }
        )
    )
    monkeypatch.chdir(tmp_path)

    config = DfaasConfig(functions=[DfaasFunctionConfig(name="figlet")])
    planner = _make_planner(config)

    run_id = planner._resolve_run_id()

    assert run_id == "run-2026-03-23"


def test_resolve_run_id_falls_back_when_generated_config_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "lb_plugins.plugins.dfaas.services.run_execution.time.time",
        lambda: 123.4,
    )

    config = DfaasConfig(functions=[DfaasFunctionConfig(name="figlet")])
    planner = _make_planner(config)

    assert planner._resolve_run_id() == "run-123"


def test_resolve_run_id_falls_back_when_generated_config_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "benchmark_config.generated.json").write_text("{not-json")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "lb_plugins.plugins.dfaas.services.run_execution.time.time",
        lambda: 123.4,
    )

    config = DfaasConfig(functions=[DfaasFunctionConfig(name="figlet")])
    planner = _make_planner(config)

    assert planner._resolve_run_id() == "run-123"
