"""
eBPF collector implementation for kernel-level tracing.

This module provides integration with eBPF tools from the BPF Compiler Collection (bcc).
"""

import logging
import os
import platform
import subprocess
from typing import Dict, Any, List, Optional

from ._base_collector import BaseCollector


logger = logging.getLogger(__name__)


class EBPFCollector(BaseCollector):
    """Metric collector using eBPF tools."""
    
    def __init__(
        self, 
        name: str = "EBPFCollector",
        interval_seconds: float = 1.0,
        tools: Optional[List[str]] = None
    ):
        """
        Initialize the eBPF collector.
        
        Args:
            name: Name of the collector
            interval_seconds: Sampling interval in seconds
            tools: List of eBPF tools to run (e.g., ['execsnoop', 'biosnoop'])
        """
        super().__init__(name, interval_seconds)
        self.tools = tools or []
        self._processes: Dict[str, subprocess.Popen] = {}
        
    def _validate_environment(self) -> bool:
        """
        Validate that eBPF can run in the current environment.
        
        Returns:
            True if the environment is valid, False otherwise
        """
        # Check if running on Linux
        if platform.system() != "Linux":
            logger.error("eBPF is only supported on Linux")
            return False
            
        # Check for root privileges
        if os.geteuid() != 0:
            logger.error("eBPF requires root privileges")
            return False
            
        # Check if BCC tools are available
        for tool in self.tools:
            try:
                result = subprocess.run(
                    ["which", tool],
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    logger.error(f"eBPF tool '{tool}' not found")
                    return False
            except Exception as e:
                logger.error(f"Error checking for tool '{tool}': {e}")
                return False
                
        return True
    
    def _collect_metrics(self) -> Dict[str, Any]:
        """
        Collect metrics from eBPF tools.
        
        Returns:
            Dictionary containing metric names and their values
        """
        metrics = {}
        
        # For demonstration, return placeholder data
        # In a real implementation, this would parse output from eBPF tools
        for tool in self.tools:
            if tool == "execsnoop":
                metrics["process_execs"] = 0
            elif tool == "biosnoop":
                metrics["block_io_ops"] = 0
            elif tool == "tcpconnect":
                metrics["tcp_connections"] = 0
            elif tool == "cachestat":
                metrics["cache_hits"] = 0
                metrics["cache_misses"] = 0
                
        return metrics
    
    def start(self) -> None:
        """Start the eBPF tools in background processes."""
        if not self._validate_environment():
            raise RuntimeError("eBPF environment validation failed")
            
        # Start base collector
        super().start()
        
        # Start eBPF tool processes
        for tool in self.tools:
            try:
                # Start tool with JSON output if supported
                cmd = [tool, "-j"] if tool in ["execsnoop", "biosnoop"] else [tool]
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                self._processes[tool] = process
                logger.info(f"Started eBPF tool: {tool}")
                
            except Exception as e:
                logger.error(f"Failed to start eBPF tool '{tool}': {e}")
    
    def stop(self) -> None:
        """Stop the eBPF tools and collector."""
        # Stop base collector
        super().stop()
        
        # Terminate eBPF tool processes
        for tool, process in self._processes.items():
            try:
                process.terminate()
                process.wait(timeout=5)
                logger.info(f"Stopped eBPF tool: {tool}")
            except subprocess.TimeoutExpired:
                process.kill()
                logger.warning(f"Force killed eBPF tool: {tool}")
            except Exception as e:
                logger.error(f"Error stopping eBPF tool '{tool}': {e}")
                
        self._processes.clear()


def aggregate_ebpf(df) -> Dict[str, float]:
    """
    Aggregate metrics collected by EBPFCollector.

    Args:
        df: DataFrame with eBPF metrics

    Returns:
        Dictionary of aggregated metrics.
    """
    if df is None or df.empty:
        return {}

    summary: Dict[str, float] = {}
    if "process_execs" in df.columns:
        summary["ebpf_process_execs_total"] = df["process_execs"].sum()
    if "block_io_ops" in df.columns:
        summary["ebpf_block_io_ops_total"] = df["block_io_ops"].sum()
    if "tcp_connections" in df.columns:
        summary["ebpf_tcp_connections_total"] = df["tcp_connections"].sum()
    if "cache_hits" in df.columns:
        hits = df["cache_hits"].sum()
        misses = df["cache_misses"].sum() if "cache_misses" in df.columns else 0
        total = hits + misses
        summary["ebpf_cache_hit_rate_pct"] = (hits / total * 100) if total else 0

    return summary
