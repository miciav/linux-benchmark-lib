"""Unit tests for metrics collection service."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from lb_runner.api import collect_metrics

pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


def test_collect_metrics_saves_only_to_rep_dir(tmp_path: Path):
    """Ensure collect_metrics saves collector data only to rep_dir, not workload_dir."""
    workload_dir = tmp_path / "workload"
    rep_dir = workload_dir / "rep1"
    workload_dir.mkdir()
    rep_dir.mkdir()

    collector = MagicMock()
    collector.name = "test_collector"
    collector.get_data.return_value = "some_data"

    # Mock save_data to actually write a file so we can check for existence
    def save_data_side_effect(path: Path):
        path.write_text("mock data")

    collector.save_data.side_effect = save_data_side_effect

    result = {"metrics": {}}
    collect_metrics([collector], workload_dir, rep_dir, "test_workload", 1, result)

    expected_filename = "test_workload_rep1_test_collector.csv"
    rep_file = rep_dir / expected_filename
    workload_file = workload_dir / expected_filename

    assert rep_file.exists(), "Collector file should exist in repetition directory"
    assert (
        not workload_file.exists()
    ), "Collector file should NOT exist in workload directory"

    assert result["metrics"]["test_collector"] == "some_data"
