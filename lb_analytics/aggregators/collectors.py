"""Collector aggregation helpers."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def aggregate_psutil(df: pd.DataFrame) -> Dict[str, float]:
    """Aggregate PSUtil collector data."""
    if df.empty:
        return {}

    summary = {}
    
    # CPU metrics
    if "cpu_percent" in df.columns:
        summary["cpu_usage_percent_avg"] = df["cpu_percent"].mean()
        summary["cpu_usage_percent_max"] = df["cpu_percent"].max()
        summary["cpu_usage_percent_p95"] = df["cpu_percent"].quantile(0.95)
    
    # Memory metrics
    if "memory_usage" in df.columns:
        summary["memory_usage_percent_avg"] = df["memory_usage"].mean()
        summary["memory_usage_percent_max"] = df["memory_usage"].max()
    
    # Disk I/O metrics
    if "disk_read_bytes" in df.columns and len(df) > 0:
        # Calculate rates (bytes per second)
        time_diff = (df.index[-1] - df.index[0]).total_seconds() if len(df) > 1 else 1
        if time_diff <= 0:
             time_diff = 1

        read_diff = df["disk_read_bytes"].iloc[-1] - df["disk_read_bytes"].iloc[0]
        write_diff = df["disk_write_bytes"].iloc[-1] - df["disk_write_bytes"].iloc[0]
        
        summary["disk_read_mbps_avg"] = (read_diff / time_diff) / (1024 * 1024)
        summary["disk_write_mbps_avg"] = (write_diff / time_diff) / (1024 * 1024)
    
    # Network I/O metrics
    if "net_bytes_sent" in df.columns and len(df) > 0:
        time_diff = (df.index[-1] - df.index[0]).total_seconds() if len(df) > 1 else 1
        if time_diff <= 0:
             time_diff = 1
        
        sent_diff = df["net_bytes_sent"].iloc[-1] - df["net_bytes_sent"].iloc[0]
        recv_diff = df["net_bytes_recv"].iloc[-1] - df["net_bytes_recv"].iloc[0]
        
        summary["network_sent_mbps_avg"] = (sent_diff / time_diff) / (1024 * 1024)
        summary["network_recv_mbps_avg"] = (recv_diff / time_diff) / (1024 * 1024)
    
    return summary


def aggregate_cli(df: pd.DataFrame) -> Dict[str, float]:
    """Aggregate CLI collector data."""
    summary = {}

    # Example: compute averages for numerical columns
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            summary[f"{col}_avg"] = float(np.mean(df[col]))
            summary[f"{col}_max"] = float(np.max(df[col]))

    return summary
