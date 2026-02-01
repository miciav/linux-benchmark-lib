import pandas as pd
import pytest

from lb_analytics.api import DataHandler

pytestmark = pytest.mark.unit_analytics



def test_data_handler_uses_registered_aggregator():
    called = {}

    def _aggregator(df: pd.DataFrame):
        called["df_type"] = type(df)
        return {"total": df["value"].sum()}

    class _FakeCollector:
        def __init__(self, aggregator):
            self.aggregator = aggregator

    collectors = {"CustomCollector": _FakeCollector(_aggregator)}

    handler = DataHandler(collectors=collectors)
    results = [
        {
            "repetition": 1,
            "metrics": {
                "CustomCollector": [
                    {"timestamp": "2024-01-01T00:00:00", "value": 1},
                    {"timestamp": "2024-01-01T00:00:01", "value": 2},
                ]
            },
            "start_time": "2024-01-01T00:00:00",
            "end_time": "2024-01-01T00:00:01",
        }
    ]

    df = handler.process_test_results("custom", results)

    assert df is not None
    assert df.loc["total", "Repetition_1"] == 3
    assert called.get("df_type") is pd.DataFrame
