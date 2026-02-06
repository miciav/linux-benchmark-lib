from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from lb_plugins.plugins.peva_faas.plugin import (
    DfaasPlugin,
    _dedupe_index_rows,
    _flatten_metrics,
)

pytestmark = [pytest.mark.unit_plugins]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_results_to_csv_returns_empty_when_no_functions(tmp_path: Path) -> None:
    plugin = DfaasPlugin()

    paths = plugin.export_results_to_csv(
        results=[{"generator_result": {"peva_faas_results": [{"foo": "bar"}]}}],
        output_dir=tmp_path,
        run_id="run-1",
        test_name="peva",
    )

    assert paths == []


def test_export_results_to_csv_writes_all_expected_artifacts(tmp_path: Path) -> None:
    plugin = DfaasPlugin()

    results = [
        {
            "repetition": 2,
            "generator_result": {
                "peva_faas_functions": ["figlet"],
                "peva_faas_results": [{"function_figlet": "figlet", "rest_seconds": 5}],
                "peva_faas_skipped": [{"function_figlet": "figlet", "rate_function_figlet": 10}],
                "peva_faas_index": [
                    {
                        "functions": ["figlet"],
                        "rates": [10],
                        "results_file": "results.csv",
                    },
                    {
                        "functions": ["figlet"],
                        "rates": [10],
                        "results_file": "results.csv",
                    },
                ],
                "peva_faas_summaries": [
                    {"config_id": "cfg-1", "iteration": 1, "summary": {"metrics": {}}}
                ],
                "peva_faas_metrics": [
                    {
                        "config_id": "cfg-1",
                        "iteration": 1,
                        "metrics": {
                            "cpu_usage_node": 10.0,
                            "functions": {"figlet": {"cpu": 1.0, "ram": 2.0, "power": 3.0}},
                        },
                    }
                ],
                "peva_faas_scripts": [
                    {"config_id": "cfg-1", "script": "export default function() {}"},
                ],
            },
        },
        {
            "repetition": 2,
            "generator_result": {
                "peva_faas_functions": ["figlet"],
                "peva_faas_index": [
                    {
                        "functions": ["figlet"],
                        "rates": [20],
                        "results_file": "results.csv",
                    }
                ],
                "peva_faas_scripts": [
                    {"config_id": "cfg-1", "script": "different script should be ignored"}
                ],
            },
        },
    ]

    paths = plugin.export_results_to_csv(
        results=results,
        output_dir=tmp_path,
        run_id="run-1",
        test_name="peva",
    )

    assert tmp_path / "results.csv" in paths
    assert tmp_path / "skipped.csv" in paths
    assert tmp_path / "index.csv" in paths
    assert tmp_path / "summaries" / "summary-cfg-1-iter1-rep2.json" in paths
    assert tmp_path / "metrics" / "metrics-cfg-1-iter1-rep2.csv" in paths
    script_path = tmp_path / "k6_scripts" / "config-cfg-1.js"
    assert script_path in paths
    assert [p.name for p in paths].count("config-cfg-1.js") == 1
    assert script_path.read_text() == "export default function() {}"

    result_rows = _read_csv_rows(tmp_path / "results.csv")
    assert len(result_rows) == 1
    assert result_rows[0]["function_figlet"] == "figlet"

    summary_payload = json.loads(
        (tmp_path / "summaries" / "summary-cfg-1-iter1-rep2.json").read_text()
    )
    assert summary_payload == {"metrics": {}}

    with (tmp_path / "index.csv").open("r", newline="") as handle:
        index_rows = list(csv.reader(handle, delimiter=";"))
    assert len(index_rows) == 3
    assert index_rows[0] == ["functions", "rates", "results_file"]


def test_dedupe_index_rows_preserves_first_occurrence() -> None:
    rows = [
        {"functions": ["figlet"], "rates": [10]},
        {"functions": ["figlet"], "rates": [10]},
        {"functions": ["figlet"], "rates": [20]},
    ]

    deduped = _dedupe_index_rows(rows)

    assert deduped == [
        {"functions": ["figlet"], "rates": [10]},
        {"functions": ["figlet"], "rates": [20]},
    ]


def test_flatten_metrics_applies_nan_defaults_and_function_values() -> None:
    row = _flatten_metrics(
        {
            "ram_usage_node": 20.0,
            "functions": {
                "figlet": {"cpu": 1.5, "ram": 2.5, "power": 3.5},
                "echo": {"cpu": 0.1},
            },
        }
    )

    assert row["cpu_usage_node"] == "nan"
    assert row["ram_usage_node"] == 20.0
    assert row["ram_usage_node_pct"] == "nan"
    assert row["power_usage_node"] == "nan"
    assert row["cpu_usage_function_figlet"] == 1.5
    assert row["ram_usage_function_figlet"] == 2.5
    assert row["power_usage_function_figlet"] == 3.5
    assert row["cpu_usage_function_echo"] == 0.1
    assert row["ram_usage_function_echo"] == "nan"
    assert row["power_usage_function_echo"] == "nan"
