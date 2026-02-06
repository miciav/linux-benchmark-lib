from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lb_plugins.plugins.peva_faas.services.run_execution as run_execution_mod
from lb_plugins.plugins.peva_faas.config import DfaasConfig, DfaasFunctionConfig
from lb_plugins.plugins.peva_faas.context import ExecutionContext
from lb_plugins.plugins.peva_faas.services.cooldown import MetricsSnapshot
from lb_plugins.plugins.peva_faas.services.run_execution import DfaasRunPlanner

pytestmark = [pytest.mark.unit_plugins]


def _make_run_planner(config: DfaasConfig) -> tuple[DfaasRunPlanner, MagicMock, MagicMock, MagicMock, MagicMock]:
    exec_ctx = ExecutionContext(host="node-1", repetition=2, total_repetitions=3)
    planner = MagicMock()
    metrics = MagicMock()
    logs = MagicMock()
    annotations = MagicMock()
    run_planner = DfaasRunPlanner(
        config=config,
        exec_ctx=exec_ctx,
        planner=planner,
        metrics_collector=metrics,
        log_manager=logs,
        annotations=annotations,
        replicas_provider=lambda _names: {"f1": 1},
    )
    return run_planner, planner, metrics, logs, annotations


def test_prepare_builds_context_and_attaches_run_services(tmp_path: Path) -> None:
    config = DfaasConfig(
        output_dir=tmp_path,
        run_id="run-abc",
        functions=[DfaasFunctionConfig(name="f1")],
    )
    run_planner, planner, metrics, logs, annotations = _make_run_planner(config)
    planner.build_function_names.return_value = ["f1"]
    planner.build_rates.return_value = [10]
    planner.build_rates_by_function.return_value = {"f1": [10]}
    planner.build_configurations.return_value = [[("f1", 10)]]
    metrics.get_node_snapshot.return_value = MetricsSnapshot(1.0, 2.0, 3.0, 4.0)
    run_planner._load_index = lambda _output_dir: {(("f1",), (10,))}  # type: ignore[method-assign]

    ctx = run_planner.prepare()

    assert ctx.function_names == ["f1"]
    assert ctx.configs == [[("f1", 10)]]
    assert ctx.existing_index == {(("f1",), (10,))}
    assert ctx.target_name == "node-1"
    assert ctx.run_id == "run-abc"
    assert ctx.output_dir == tmp_path
    assert ctx.repetition == 2
    logs.attach_handlers.assert_called_once_with(tmp_path, "run-abc")
    annotations.setup.assert_called_once()


def test_resolve_output_dir_uses_generated_config_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = DfaasConfig(functions=[DfaasFunctionConfig(name="f1")])
    run_planner, _planner, _metrics, _logs, _annotations = _make_run_planner(config)
    generated = {
        "output_dir": str(tmp_path / "benchmark_results" / "run-1"),
        "workloads": {"my_workload": {"plugin": "peva_faas"}},
    }
    monkeypatch.chdir(tmp_path)
    Path("benchmark_config.generated.json").write_text(json.dumps(generated))

    output_dir = run_planner._resolve_output_dir()

    assert output_dir == Path(generated["output_dir"]) / "my_workload"


def test_load_output_dir_from_generated_returns_none_on_parse_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = DfaasConfig(functions=[DfaasFunctionConfig(name="f1")])
    run_planner, _planner, _metrics, _logs, _annotations = _make_run_planner(config)
    monkeypatch.chdir(tmp_path)
    Path("benchmark_config.generated.json").write_text("{broken-json")

    assert run_planner._load_output_dir_from_generated() is None


def test_find_workload_name_falls_back_to_peva_name() -> None:
    assert DfaasRunPlanner._find_workload_name({"other": {"plugin": "not-peva"}}) == "peva_faas"


def test_load_index_reads_rows_and_handles_invalid_literal(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = DfaasConfig(functions=[DfaasFunctionConfig(name="f1")])
    run_planner, _planner, _metrics, _logs, _annotations = _make_run_planner(config)
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.csv"
    index_path.write_text(
        "functions;rates;results_file\n"
        "\"['f1']\";\"[10]\";results.csv\n"
    )

    assert run_planner._load_index(output_dir) == {(("f1",), (10,))}

    caplog.set_level("WARNING")
    index_path.write_text(
        "functions;rates;results_file\n"
        "\"['f1'\";\"[10]\";results.csv\n"
    )
    assert run_planner._load_index(output_dir) == set()
    assert "Invalid data in index file" in caplog.text


def test_load_index_handles_csv_reader_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config = DfaasConfig(functions=[DfaasFunctionConfig(name="f1")])
    run_planner, _planner, _metrics, _logs, _annotations = _make_run_planner(config)
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.csv"
    index_path.write_text("functions;rates;results_file\n")

    def broken_reader(*_args, **_kwargs):
        raise run_execution_mod.csv.Error("bad csv")

    monkeypatch.setattr(run_execution_mod.csv, "DictReader", broken_reader)
    caplog.set_level("WARNING")

    assert run_planner._load_index(output_dir) == set()
    assert "Could not read index file" in caplog.text


def test_resolve_run_id_uses_config_generated_and_time_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_cfg = DfaasConfig(
        run_id="cfg-run",
        functions=[DfaasFunctionConfig(name="f1")],
    )
    run_planner_fixed, _planner, _metrics, _logs, _annotations = _make_run_planner(
        fixed_cfg
    )
    assert run_planner_fixed._resolve_run_id() == "cfg-run"

    config = DfaasConfig(functions=[DfaasFunctionConfig(name="f1")])
    run_planner, _planner, _metrics, _logs, _annotations = _make_run_planner(config)
    monkeypatch.chdir(tmp_path)
    Path("benchmark_config.generated.json").write_text(
        json.dumps({"output_dir": str(tmp_path / "runs" / "run-77" / "peva_faas")})
    )
    assert run_planner._resolve_run_id() == "run-77"

    Path("benchmark_config.generated.json").unlink()
    monkeypatch.setattr(run_execution_mod.time, "time", lambda: 123)
    assert run_planner._resolve_run_id() == "run-123"
