"""Tests for incremental result persistence/export behavior."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import lb_runner.services.result_persister as result_persister_mod
from lb_runner.services.result_persister import ResultPersister


def test_process_results_writes_aggregate_json_and_exports_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    plugin = MagicMock()
    plugin.export_results_to_csv.return_value = []
    persister = ResultPersister(run_id="run-1")
    results_path = tmp_path / "stress_ng_results.json"
    merge_spy = MagicMock(wraps=result_persister_mod.merge_results)
    monkeypatch.setattr(result_persister_mod, "merge_results", merge_spy)

    persister.process_results(
        plugin,
        [{"repetition": 1, "value": "a"}],
        tmp_path,
        "stress_ng",
        export_results=False,
    )

    assert results_path.exists()
    assert json.loads(results_path.read_text()) == [{"repetition": 1, "value": "a"}]
    assert plugin.export_results_to_csv.call_count == 0
    assert merge_spy.call_count == 1

    persister.process_results(
        plugin,
        [{"repetition": 2, "value": "b"}],
        tmp_path,
        "stress_ng",
        export_results=False,
    )

    assert json.loads(results_path.read_text()) == [
        {"repetition": 1, "value": "a"},
        {"repetition": 2, "value": "b"},
    ]
    assert plugin.export_results_to_csv.call_count == 0
    assert merge_spy.call_count == 1

    persister.process_results(
        plugin,
        [],
        tmp_path,
        "stress_ng",
        export_results=True,
    )

    assert plugin.export_results_to_csv.call_count == 1
    exported = plugin.export_results_to_csv.call_args.kwargs["results"]
    assert exported == [
        {"repetition": 1, "value": "a"},
        {"repetition": 2, "value": "b"},
    ]

    saved = json.loads(results_path.read_text())
    assert saved == [
        {"repetition": 1, "value": "a"},
        {"repetition": 2, "value": "b"},
    ]
    assert merge_spy.call_count == 1


def test_process_results_cache_is_instance_local(
    monkeypatch,
    tmp_path: Path,
) -> None:
    plugin = MagicMock()
    plugin.export_results_to_csv.return_value = []
    merge_spy = MagicMock(wraps=result_persister_mod.merge_results)
    monkeypatch.setattr(result_persister_mod, "merge_results", merge_spy)

    first = ResultPersister(run_id="run-1")
    first.process_results(
        plugin,
        [{"repetition": 1, "value": "a"}],
        tmp_path,
        "stress_ng",
        export_results=False,
    )

    second = ResultPersister(run_id="run-2")
    second.process_results(
        plugin,
        [{"repetition": 2, "value": "b"}],
        tmp_path,
        "stress_ng",
        export_results=True,
    )

    results_path = tmp_path / "stress_ng_results.json"
    assert json.loads(results_path.read_text()) == [
        {"repetition": 1, "value": "a"},
        {"repetition": 2, "value": "b"},
    ]
    assert merge_spy.call_count == 2
    assert plugin.export_results_to_csv.call_count == 1
