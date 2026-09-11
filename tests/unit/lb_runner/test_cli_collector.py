"""Tests for CLICollector parsing and robustness."""

import pandas as pd
import pytest

from lb_runner.api import aggregate_cli
from lb_runner.metric_collectors.cli_collector import CLICollector, _merge_parsed

pytestmark = pytest.mark.unit_runner


def test_aggregate_cli_handles_numeric_columns():
    df = pd.DataFrame(
        [
            {"r": 1, "b": 0, "si": 5.0, "so": 2.0},
            {"r": 3, "b": 1, "si": 7.0, "so": 4.0},
        ]
    )
    result = aggregate_cli(df)
    assert result["processes_running_avg"] == 2.0
    assert result["processes_blocked_avg"] == 0.5
    assert result["swap_in_kbps_avg"] == 6.0
    assert result["swap_out_kbps_avg"] == 3.0


def test_aggregate_cli_ignores_non_numeric():
    df = pd.DataFrame([{"r": 2, "note": "x"}])
    result = aggregate_cli(df)
    assert "note_avg" not in result
    assert result["processes_running_avg"] == 2.0


def test_missing_optional_tool_is_dropped_not_fatal(monkeypatch):
    """One unavailable tool must not stop the collector using the others."""
    monkeypatch.setattr(
        CLICollector,
        "_is_tool_available",
        lambda self, tool: tool == "vmstat",
    )
    collector = CLICollector(
        interval_seconds=1.0,
        commands=["vmstat 1 1", "definitely-not-a-tool 1 1"],
    )

    assert collector._validate_environment() is True
    assert collector.commands == ["vmstat 1 1"]


def test_no_available_tool_is_still_fatal(monkeypatch):
    """With nothing left to run, the collector cannot start."""
    monkeypatch.setattr(CLICollector, "_is_tool_available", lambda self, tool: False)
    collector = CLICollector(interval_seconds=1.0, commands=["vmstat 1 1"])

    assert collector._validate_environment() is False


def test_validate_environment_splits_quoted_tool_path(monkeypatch):
    """A quoted tool path resolves to the same name _collect_metrics uses."""
    monkeypatch.setattr(
        CLICollector,
        "_is_tool_available",
        lambda self, tool: tool == "/usr/bin/sar",
    )
    collector = CLICollector(interval_seconds=1.0, commands=['"/usr/bin/sar" -u 1 1'])

    assert collector._validate_environment() is True
    assert collector.commands == ['"/usr/bin/sar" -u 1 1']


def test_single_row_list_is_merged_flat():
    """One row keeps the flat schema the aggregators expect."""
    assert _merge_parsed("vmstat", [{"runnable_procs": 1}]) == {"runnable_procs": 1}


def test_multi_row_list_keeps_every_row():
    """Keep every row jc returns; none may be dropped."""
    rows = [
        {"device": "loop0", "tps": 1.0},
        {"device": "nvme0n1", "tps": 79.42},
    ]

    merged = _merge_parsed("iostat", rows)

    assert merged["device"] == "loop0"
    assert merged["iostat_rows"] == rows


def test_non_list_passes_through():
    assert _merge_parsed("sar", {"user_time": 5}) == {"user_time": 5}
    assert _merge_parsed("sar", None) == {}
