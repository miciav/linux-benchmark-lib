"""CLI unit tests for runs/analyze commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lb_ui.cli.app import app
from lb_controller.api import ConfigService

pytestmark = [pytest.mark.unit_ui]


def test_cli_runs_list_and_analyze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    # Avoid reading user-level config defaults (non-hermetic).
    import lb_ui.cli as cli

    monkeypatch.setattr(cli, "config_service", ConfigService(config_home=tmp_path / "config"))

    output_root = tmp_path / "benchmark_results"
    run_root = output_root / "run-20240101-000000" / "host1" / "stress_ng"
    run_root.mkdir(parents=True)
    (output_root / "run-20240101-000000" / "host1" / "exports").mkdir(parents=True)

    results = [
        {
            "test_name": "stress_ng",
            "repetition": 1,
            "start_time": "2024-01-01T00:00:00",
            "end_time": "2024-01-01T00:00:01",
            "metrics": {
                "PSUtilCollector": [
                    {"timestamp": "2024-01-01T00:00:00", "cpu_percent": 1.0},
                    {"timestamp": "2024-01-01T00:00:01", "cpu_percent": 2.0},
                ]
            },
        }
    ]
    (run_root / "stress_ng_results.json").write_text(json.dumps(results))

    res_list = runner.invoke(app, ["runs", "list", "--root", str(output_root)])
    assert res_list.exit_code == 0

    res_analyze = runner.invoke(
        app,
        [
            "analyze",
            "run-20240101-000000",
            "--root",
            str(output_root),
        ],
    )
    assert res_analyze.exit_code == 0
    out_csv = (
        output_root
        / "run-20240101-000000"
        / "host1"
        / "exports"
        / "stress_ng_aggregated.csv"
    )
    assert out_csv.exists()
