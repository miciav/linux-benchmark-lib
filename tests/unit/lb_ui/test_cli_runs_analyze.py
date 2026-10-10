"""CLI tests for lb runs analyze (experiment unification)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lb_app.api import ConfigService
from lb_runner.api import BenchmarkConfig
from tests.helpers.analytics_runs import collected_run

pytestmark = [pytest.mark.unit_ui]


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import lb_ui.api as cli

    monkeypatch.setattr(
        cli.ctx_store, "config_service", ConfigService(config_home=tmp_path / "cfg")
    )
    root = tmp_path / "benchmark_results"
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    collected_run(root, "run-3", "other", "dd", "2026-10-09T09:00:00")
    config = tmp_path / "config.json"
    BenchmarkConfig(output_dir=root, data_export_dir=tmp_path / "exports").save(config)

    def invoke(*args: str):
        return CliRunner().invoke(
            cli.app, ["runs", "analyze", *args, "--config", str(config)]
        )

    return invoke, tmp_path / "exports"


def test_an_experiment_is_unified(setup):
    invoke, exports = setup
    result = invoke("--experiment", "tuning")
    assert result.exit_code == 0, result.output
    assert (exports / "tuning" / "results.parquet").exists()
    assert "Equivalent command" in result.output


def test_the_folder_is_unified(setup):
    invoke, exports = setup
    result = invoke("--folder")
    assert result.exit_code == 0, result.output
    assert (exports / "_folders" / "benchmark_results" / "runs.parquet").exists()


def test_experiment_and_folder_are_exclusive(setup):
    invoke, _ = setup
    result = invoke("--experiment", "tuning", "--folder")
    assert result.exit_code == 1
    assert "not both" in result.output


def test_without_a_terminal_a_target_is_required(setup):
    invoke, _ = setup
    result = invoke()
    assert result.exit_code == 1
    assert "--experiment ID or --folder" in result.output


def test_an_unknown_experiment_lists_recent_ones(setup):
    invoke, _ = setup
    result = invoke("--experiment", "nope")
    assert result.exit_code == 1
    assert "tuning" in result.output


def test_filters_that_leave_nothing_fail(setup):
    invoke, exports = setup
    result = invoke("--experiment", "tuning", "--host", "nobody")
    assert result.exit_code == 1
    assert "Nothing to unify" in result.output
    assert not (exports / "tuning").exists()


def test_load_errors_warn_but_still_write(setup, tmp_path):
    invoke, exports = setup
    broken = tmp_path / "benchmark_results" / "run-1" / "h1" / "fio" / "fio_plugin.csv"
    broken.write_text('"unterminated\n')
    result = invoke("--experiment", "tuning")
    assert result.exit_code == 0, result.output
    assert "load error" in result.output
    assert (exports / "tuning" / "results.parquet").exists()


def test_the_equivalent_command_works_from_any_folder(setup, tmp_path, monkeypatch):
    import lb_ui.api as cli

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli.app, ["runs", "analyze", "--experiment", "tuning", "-c", "config.json"]
    )
    assert result.exit_code == 0, result.output
    # Rich wraps long paths, so compare without whitespace.
    flat = "".join(result.output.split())
    assert f"--config{tmp_path / 'config.json'}" in flat
