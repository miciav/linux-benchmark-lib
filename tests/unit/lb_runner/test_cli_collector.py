"""Tests for CLICollector parsing and robustness."""

import pytest
import pandas as pd
from lb_runner.api import aggregate_cli

import pytest

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
