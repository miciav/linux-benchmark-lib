import pandas as pd

from lb_analytics.aggregators.collectors import aggregate_cli, aggregate_psutil

import pytest

pytestmark = pytest.mark.analytics

def test_aggregate_psutil_empty_df_returns_empty():
    df = pd.DataFrame()
    assert aggregate_psutil(df) == {}


def test_aggregate_psutil_computes_rates_and_percentiles():
    data = [
        {
            "timestamp": "2024-01-01T00:00:00",
            "cpu_percent": 10.0,
            "memory_usage": 5.0,
            "disk_read_bytes": 0,
            "disk_write_bytes": 0,
            "net_bytes_sent": 0,
            "net_bytes_recv": 0,
        },
        {
            "timestamp": "2024-01-01T00:00:01",
            "cpu_percent": 30.0,
            "memory_usage": 9.0,
            "disk_read_bytes": 1024,
            "disk_write_bytes": 2048,
            "net_bytes_sent": 1024,
            "net_bytes_recv": 4096,
        },
    ]
    df = pd.DataFrame(data).set_index(pd.to_datetime([row["timestamp"] for row in data]))
    result = aggregate_psutil(df)
    assert result["cpu_usage_percent_avg"] == 20.0
    assert result["memory_usage_percent_max"] == 9.0
    assert result["disk_read_mbps_avg"] > 0
    assert result["network_recv_mbps_avg"] > 0


def test_aggregate_cli_numeric_columns():
    df = pd.DataFrame(
        [
            {"foo": 1, "bar": 5},
            {"foo": 3, "bar": 7},
        ]
    )
    result = aggregate_cli(df)
    assert result["foo_avg"] == 2.0
    assert result["foo_max"] == 3
    assert result["bar_avg"] == 6.0
