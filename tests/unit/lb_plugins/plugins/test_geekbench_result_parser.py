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
