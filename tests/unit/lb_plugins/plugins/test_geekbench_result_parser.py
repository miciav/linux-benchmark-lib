from __future__ import annotations

import json
from pathlib import Path

import pytest

from lb_plugins.plugins.geekbench.plugin import GeekbenchResultParser

pytestmark = [pytest.mark.unit_plugins]


def test_geekbench_result_parser_collects_rows(tmp_path: Path) -> None:
    payload = {
        "single_core_score": 111,
        "multi_core_score": 222,
        "version": "6.3.0",
        "benchmarks": [{"name": "foo", "score": 12}],
    }
    json_path = tmp_path / "geekbench_result.json"
    json_path.write_text(json.dumps(payload))

    results = [
        {
            "repetition": 1,
            "generator_result": {"json_result": str(json_path), "returncode": 0},
            "success": True,
            "duration_seconds": 12.0,
        }
    ]

    parser = GeekbenchResultParser(tmp_path, "6.3.0")
    summary_rows, subtest_rows = parser.collect_rows(
        results,
        run_id="run-1",
        test_name="geekbench",
    )

    assert summary_rows[0]["single_core_score"] == 111
    assert summary_rows[0]["multi_core_score"] == 222
    assert subtest_rows[0]["subtest"] == "foo"
    assert subtest_rows[0]["score"] == 12


def test_geekbench_export_keeps_json_with_collected_output(tmp_path: Path) -> None:
    from lb_plugins.api import GeekbenchPlugin

    remote_dir = tmp_path / "lb_geekbench"
    remote_dir.mkdir()
    results = []
    for rep, score in ((1, 100), (2, 200)):
        src = remote_dir / f"geekbench_result_{rep}.json"
        src.write_text(json.dumps({"single_core_score": score}))
        results.append(
            {"repetition": rep, "generator_result": {"json_result": str(src)}}
        )
    workload_dir = tmp_path / "geekbench"
    GeekbenchPlugin().export_results_to_csv(results, workload_dir, "r", "geekbench")

    # On the controller the remote paths do not exist; the copies must be used.
    for path in remote_dir.iterdir():
        path.unlink()
    rows, _ = GeekbenchResultParser(workload_dir, "6.3.0").collect_rows(
        results, run_id="r", test_name="geekbench"
    )
    assert [row["single_core_score"] for row in rows] == [100, 200]
