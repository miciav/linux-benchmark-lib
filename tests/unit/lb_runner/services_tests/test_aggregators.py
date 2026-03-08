"""Aggregation helper tests."""

from __future__ import annotations

import pandas as pd

from lb_runner.metric_collectors.aggregators import aggregate_psutil


def test_aggregate_psutil_tolerates_missing_disk_write_column() -> None:
    df = pd.DataFrame(
        {
            "disk_read_bytes": [0, 1024],
        },
        index=pd.to_datetime(["2024-01-01T00:00:00", "2024-01-01T00:00:01"]),
    )

    summary = aggregate_psutil(df)

    assert summary == {}


def test_aggregate_psutil_tolerates_missing_net_recv_column() -> None:
    df = pd.DataFrame(
        {
            "net_bytes_sent": [0, 2048],
        },
        index=pd.to_datetime(["2024-01-01T00:00:00", "2024-01-01T00:00:01"]),
    )

    summary = aggregate_psutil(df)

    assert summary == {}
