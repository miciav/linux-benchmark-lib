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

