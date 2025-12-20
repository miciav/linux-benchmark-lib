"""Aggregation helpers for collector metrics."""

from __future__ import annotations

from typing import Dict


def aggregate_psutil(df) -> Dict[str, float]:
    """
    Aggregate metrics collected by PSUtilCollector.

    Args:
        df: DataFrame with PSUtil metrics (timestamp as index recommended)

    Returns:
        Dictionary of aggregated metrics.
    """
    if df is None or df.empty:
        return {}

    summary: Dict[str, float] = {}

    if "cpu_percent" in df.columns:
        summary["cpu_usage_percent_avg"] = df["cpu_percent"].mean()
        summary["cpu_usage_percent_max"] = df["cpu_percent"].max()
        summary["cpu_usage_percent_p95"] = df["cpu_percent"].quantile(0.95)

    if "memory_usage" in df.columns:
        summary["memory_usage_percent_avg"] = df["memory_usage"].mean()
        summary["memory_usage_percent_max"] = df["memory_usage"].max()

    if "disk_read_bytes" in df.columns and len(df) > 0:
        time_diff = (df.index[-1] - df.index[0]).total_seconds() if len(df) > 1 else 1
        if time_diff <= 0:
            time_diff = 1

        read_diff = df["disk_read_bytes"].iloc[-1] - df["disk_read_bytes"].iloc[0]
        write_diff = df["disk_write_bytes"].iloc[-1] - df["disk_write_bytes"].iloc[0]

        summary["disk_read_mbps_avg"] = (read_diff / time_diff) / (1024 * 1024)
        summary["disk_write_mbps_avg"] = (write_diff / time_diff) / (1024 * 1024)

    if "net_bytes_sent" in df.columns and len(df) > 0:
        time_diff = (df.index[-1] - df.index[0]).total_seconds() if len(df) > 1 else 1
        if time_diff <= 0:
            time_diff = 1

        sent_diff = df["net_bytes_sent"].iloc[-1] - df["net_bytes_sent"].iloc[0]
        recv_diff = df["net_bytes_recv"].iloc[-1] - df["net_bytes_recv"].iloc[0]

        summary["network_sent_mbps_avg"] = (sent_diff / time_diff) / (1024 * 1024)
        summary["network_recv_mbps_avg"] = (recv_diff / time_diff) / (1024 * 1024)

    return summary


def aggregate_cli(df) -> Dict[str, float]:
    """
    Aggregate metrics collected by CLICollector.

    Args:
        df: DataFrame with CLI metrics

    Returns:
        Dictionary of aggregated metrics.
    """
    if df is None or df.empty:
        return {}

    summary: Dict[str, float] = {}
    if "r" in df.columns:
        summary["processes_running_avg"] = df["r"].mean()
    if "b" in df.columns:
        summary["processes_blocked_avg"] = df["b"].mean()
    if "si" in df.columns:
        summary["swap_in_kbps_avg"] = df["si"].mean()
    if "so" in df.columns:
        summary["swap_out_kbps_avg"] = df["so"].mean()

    return summary
