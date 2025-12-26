import json
from pathlib import Path

from lb_analytics.api import DataHandler

import pytest

pytestmark = pytest.mark.unit_analytics

def test_data_handler_fallback_psutil_aggregator():
    handler = DataHandler()
    data_path = Path(__file__).resolve().parent.parent.parent / "fixtures" / "collector_psutil.json"
    sample = json.loads(data_path.read_text())
    results = [
        {
            "repetition": 1,
            "metrics": {
                "PSUtilCollector": sample
            },
            "start_time": "2024-01-01T00:00:00",
            "end_time": "2024-01-01T00:00:01",
        }
    ]

    df = handler.process_test_results("psutil", results)

    assert df is not None
    assert "cpu_usage_percent_avg" in df.index
    assert df.loc["cpu_usage_percent_avg", "Repetition_1"] == 60.0
    assert df.loc["memory_usage_percent_max", "Repetition_1"] == 22.0


def test_data_handler_fallback_cli_aggregator():
    handler = DataHandler()
    data_path = Path(__file__).resolve().parent.parent.parent / "fixtures" / "collector_cli.json"
    sample = json.loads(data_path.read_text())
    results = [
        {
            "repetition": 1,
            "metrics": {
                "CLICollector": sample
            },
            "start_time": "2024-01-01T00:00:00",
            "end_time": "2024-01-01T00:00:01",
        }
    ]

    df = handler.process_test_results("cli", results)

    assert df is not None
    assert df.loc["foo_avg", "Repetition_1"] == 2.0
    assert df.loc["foo_max", "Repetition_1"] == 3.0


def test_data_handler_handles_aggregator_exception():
    class BadPlugin:
        def __init__(self):
            self.aggregator = lambda df: (_ for _ in ()).throw(RuntimeError("fail"))  # generator to throw

    handler = DataHandler(collectors={"Bad": BadPlugin()})
    results = [
        {
            "repetition": 1,
            "metrics": {"Bad": [{"timestamp": "2024-01-01T00:00:00", "x": 1}]},
            "start_time": "2024-01-01T00:00:00",
            "end_time": "2024-01-01T00:00:01",
        }
    ]
    df = handler.process_test_results("bad", results)
    # Aggregation fails silently; result is empty DataFrame
    assert df is None or df.empty
