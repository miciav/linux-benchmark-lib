"""Collector aggregation helpers."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def _safe_time_diff_seconds(index: pd.Index) -> float:
    if len(index) <= 1:
        return 1.0
    time_diff = (index[-1] - index[0]).total_seconds()
    return time_diff if time_diff > 0 else 1.0


def _update_cpu_metrics(summary: Dict[str, float], df: pd.DataFrame) -> None:
    if "cpu_percent" not in df.columns:
        return
    summary["cpu_usage_percent_avg"] = df["cpu_percent"].mean()
    summary["cpu_usage_percent_max"] = df["cpu_percent"].max()
    summary["cpu_usage_percent_p95"] = df["cpu_percent"].quantile(0.95)


def _update_memory_metrics(summary: Dict[str, float], df: pd.DataFrame) -> None:
    if "memory_usage" not in df.columns:
        return
    summary["memory_usage_percent_avg"] = df["memory_usage"].mean()
    summary["memory_usage_percent_max"] = df["memory_usage"].max()


def _update_disk_metrics(summary: Dict[str, float], df: pd.DataFrame) -> None:
    time_diff = _safe_time_diff_seconds(df.index)
    if "disk_read_bytes" in df.columns:
        read_diff = df["disk_read_bytes"].iloc[-1] - df["disk_read_bytes"].iloc[0]
        summary["disk_read_mbps_avg"] = (read_diff / time_diff) / (1024 * 1024)
    if "disk_write_bytes" in df.columns:
        write_diff = df["disk_write_bytes"].iloc[-1] - df["disk_write_bytes"].iloc[0]
        summary["disk_write_mbps_avg"] = (write_diff / time_diff) / (1024 * 1024)
    if "disk_read_mbps_avg" not in summary and "disk_write_mbps_avg" not in summary:
        return


def _update_network_metrics(summary: Dict[str, float], df: pd.DataFrame) -> None:
    time_diff = _safe_time_diff_seconds(df.index)
    if "net_bytes_sent" in df.columns:
        sent_diff = df["net_bytes_sent"].iloc[-1] - df["net_bytes_sent"].iloc[0]
        summary["network_sent_mbps_avg"] = (sent_diff / time_diff) / (1024 * 1024)
    if "net_bytes_recv" in df.columns:
        recv_diff = df["net_bytes_recv"].iloc[-1] - df["net_bytes_recv"].iloc[0]
        summary["network_recv_mbps_avg"] = (recv_diff / time_diff) / (1024 * 1024)
    if (
        "network_sent_mbps_avg" not in summary
        and "network_recv_mbps_avg" not in summary
    ):
        return


def aggregate_psutil(df: pd.DataFrame) -> Dict[str, float]:
    """Aggregate PSUtil collector data."""
    if df.empty:
        return {}

    summary: Dict[str, float] = {}
    _update_cpu_metrics(summary, df)
    _update_memory_metrics(summary, df)
    _update_disk_metrics(summary, df)
    _update_network_metrics(summary, df)

    return summary


def aggregate_cli(df: pd.DataFrame) -> Dict[str, float]:
    """Aggregate CLI collector data."""
    summary: Dict[str, float] = {}

    # Example: compute averages for numerical columns
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            summary[f"{col}_avg"] = float(np.mean(df[col]))
            summary[f"{col}_max"] = float(np.max(df[col]))

    return summary
