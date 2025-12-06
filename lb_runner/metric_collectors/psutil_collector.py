"""
PSUtil collector implementation for high-level system metric collection.

This module collects system metrics using the psutil library.
"""

import logging
from typing import Dict, Any

import psutil

from ._base_collector import BaseCollector


logger = logging.getLogger(__name__)


class PSUtilCollector(BaseCollector):
    """Metric collector using psutil."""
    
    def __init__(self, name: str = "PSUtilCollector", interval_seconds: float = 1.0):
        """
        Initialize the PSUtil collector.

        Args:
            name: Name of the collector
            interval_seconds: Sampling interval in seconds
        """
        super().__init__(name, interval_seconds)

    def _collect_metrics(self) -> Dict[str, Any]:
        """
        Collect metrics using psutil.

        Returns:
            Dictionary containing metric names and their values
        """
        metrics = {}
        try:
            metrics["cpu_percent"] = psutil.cpu_percent(interval=None)
            metrics["memory_usage"] = psutil.virtual_memory().percent
            disk_io = psutil.disk_io_counters()
            metrics["disk_read_bytes"] = disk_io.read_bytes
            metrics["disk_write_bytes"] = disk_io.write_bytes
            net_io = psutil.net_io_counters()
            metrics["net_bytes_sent"] = net_io.bytes_sent
            metrics["net_bytes_recv"] = net_io.bytes_recv
            
        except Exception as e:
            logger.error(f"Error collecting psutil data: {e}")

        return metrics

    def _validate_environment(self) -> bool:
        """
        Validate that the psutil can run in the current environment.

        Returns:
            True if the environment is valid, False otherwise
        """
        # Assume psutil is always available in Python environment
        return True


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
