"""Tests for CLICollector parsing and robustness."""

import subprocess

import jc
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
    """A quoted tool path is checked against the binary it actually names."""
    monkeypatch.setattr(
        CLICollector,
        "_is_tool_available",
        lambda self, tool: tool == "/usr/bin/sar",
    )
    collector = CLICollector(interval_seconds=1.0, commands=['"/usr/bin/sar" -u 1 1'])

    assert collector._validate_environment() is True
    assert collector.commands == ['"/usr/bin/sar" -u 1 1']


def test_quoted_path_command_reaches_jc_with_bare_tool_name(monkeypatch):
    """A quoted tool path must still collect, not silently disable the command."""
    parsers = []

    def fake_parse(parser, output):
        parsers.append(parser)
        if "/" in parser:  # jc resolves parsers by bare tool name only
            raise jc.exceptions.ParseError("This parser is disabled.")
        return {"iostat_tps": 1.0}

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="bare output\n")

    monkeypatch.setattr(jc, "parse", fake_parse)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        CLICollector,
        "_is_tool_available",
        lambda self, tool: tool == "/usr/bin/iostat",
    )
    collector = CLICollector(
        interval_seconds=1.0, commands=['"/usr/bin/iostat" -d 1 1']
    )

    assert collector._validate_environment() is True
    metrics = collector._collect_metrics()

    assert parsers == ["iostat"]
    assert collector._failed_commands == set()
    assert metrics == {"iostat_tps": 1.0}


def test_quoted_path_sar_command_is_parsed_not_disabled(monkeypatch):
    """The sar special case runs before jc, so pin that route separately."""

    def fake_run(*args, **kwargs):
        stdout = (
            "Linux 6.17.0 (host)  09/11/26  _x86_64_  (8 CPU)\n"
            "\n"
            "12:00:00  CPU  %user  %nice  %system  %iowait  %steal  %idle\n"
            "12:00:01  all   1.00   0.00     2.00     0.50    0.00   96.50\n"
        )
        return subprocess.CompletedProcess(args[0], 0, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        CLICollector,
        "_is_tool_available",
        lambda self, tool: tool == "/usr/bin/sar",
    )
    collector = CLICollector(interval_seconds=1.0, commands=['"/usr/bin/sar" -u 1 1'])

    assert collector._validate_environment() is True
    metrics = collector._collect_metrics()

    assert collector._failed_commands == set()
    assert metrics == {
        "sar_user_pct": 1.0,
        "sar_nice_pct": 0.0,
        "sar_system_pct": 2.0,
        "sar_iowait_pct": 0.5,
        "sar_steal_pct": 0.0,
        "sar_idle_pct": 96.5,
    }


def test_unparseable_command_is_dropped_not_fatal(monkeypatch):
    """A malformed config entry must warn and drop, never abort the run."""
    monkeypatch.setattr(
        CLICollector,
        "_is_tool_available",
        lambda self, tool: tool == "sar",
    )
    collector = CLICollector(
        interval_seconds=1.0,
        commands=["sar -u 1 1", '"unterminated -u 1', ""],
    )

    assert collector._validate_environment() is True
    assert collector.commands == ["sar -u 1 1"]


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


def test_aggregate_cli_handles_current_jc_column_names():
    """The jc 1.25 vmstat rename must not stop the aggregator summarising.

    Verified against jc 1.25.6: its vmstat parser emits runnable_procs,
    uninterruptible_sleeping_procs, swap_in and swap_out.
    """
    df = pd.DataFrame(
        [
            {
                "runnable_procs": 1,
                "uninterruptible_sleeping_procs": 0,
                "swap_in": 5.0,
                "swap_out": 2.0,
            },
            {
                "runnable_procs": 3,
                "uninterruptible_sleeping_procs": 1,
                "swap_in": 7.0,
                "swap_out": 4.0,
            },
        ]
    )

    result = aggregate_cli(df)

    assert result["processes_running_avg"] == 2.0
    assert result["processes_blocked_avg"] == 0.5
    assert result["swap_in_kbps_avg"] == 6.0
    assert result["swap_out_kbps_avg"] == 3.0
