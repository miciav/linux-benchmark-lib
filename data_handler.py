"""
Data handler module for processing and aggregating benchmark data.

This module is responsible for transforming raw metric data into aggregated
DataFrames suitable for analysis and reporting.
"""

import logging
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from datetime import datetime


logger = logging.getLogger(__name__)


class DataHandler:
    """Handler for processing and aggregating benchmark data."""
    
    def __init__(self):
        """Initialize the data handler."""
        self.aggregation_methods = {
            "cpu": "mean",
            "memory": "mean",
            "disk": "sum",
            "network": "sum",
            "iops": "mean",
            "latency": "mean",
            "throughput": "mean",
        }
    
    def process_test_results(
        self,
        test_name: str,
        results: List[Dict[str, Any]]
    ) -> Optional[pd.DataFrame]:
        """
        Process test results and create aggregated DataFrame.
        
        Args:
            test_name: Name of the test
            results: List of test result dictionaries
            
        Returns:
            DataFrame with metrics as index and repetitions as columns
        """
        if not results:
            logger.warning(f"No results to process for test {test_name}")
            return None
        
        # Process each repetition
        repetition_summaries = []
        
        for result in results:
            rep_num = result["repetition"]
            metrics = result["metrics"]
            
            # Extract and aggregate metrics from each collector
            rep_summary = {}
            
            for collector_name, collector_data in metrics.items():
                if not collector_data:
                    continue
                
                # Convert to DataFrame for easier processing
                df = pd.DataFrame(collector_data)
                
                # Convert timestamp to datetime and set as index if present
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    df.set_index("timestamp", inplace=True)
                
                # Process based on collector type
                if collector_name == "PSUtilCollector":
                    rep_summary.update(self._process_psutil_data(df))
                elif collector_name == "CLICollector":
                    rep_summary.update(self._process_cli_data(df))
                elif collector_name == "PerfCollector":
                    rep_summary.update(self._process_perf_data(df))
                elif collector_name == "EBPFCollector":
                    rep_summary.update(self._process_ebpf_data(df))
            
            repetition_summaries.append({
                f"Repetition_{rep_num}": rep_summary
            })
        
        # Create final DataFrame with metrics as index and repetitions as columns
        if not repetition_summaries:
            return None
        
        # Combine all repetition data
        combined_data = {}
        for rep_dict in repetition_summaries:
            for rep_name, metrics in rep_dict.items():
                combined_data[rep_name] = metrics
        
        # Create DataFrame and transpose so metrics are index
        df = pd.DataFrame(combined_data).T
        final_df = df.T  # Transpose so metrics are rows
        
        # Sort index (metric names)
        final_df.sort_index(inplace=True)
        
        logger.info(f"Created aggregated DataFrame for {test_name} with shape {final_df.shape}")
        
        return final_df
    
    def _process_psutil_data(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Process PSUtil collector data.
        
        Args:
            df: DataFrame with PSUtil metrics
            
        Returns:
            Dictionary of aggregated metrics
        """
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
        if "disk_read_bytes" in df.columns:
            # Calculate rates (bytes per second)
            time_diff = (df.index[-1] - df.index[0]).total_seconds() if len(df) > 1 else 1
            
            read_diff = df["disk_read_bytes"].iloc[-1] - df["disk_read_bytes"].iloc[0]
            write_diff = df["disk_write_bytes"].iloc[-1] - df["disk_write_bytes"].iloc[0]
            
            summary["disk_read_mbps_avg"] = (read_diff / time_diff) / (1024 * 1024)
            summary["disk_write_mbps_avg"] = (write_diff / time_diff) / (1024 * 1024)
        
        # Network I/O metrics
        if "net_bytes_sent" in df.columns:
            time_diff = (df.index[-1] - df.index[0]).total_seconds() if len(df) > 1 else 1
            
            sent_diff = df["net_bytes_sent"].iloc[-1] - df["net_bytes_sent"].iloc[0]
            recv_diff = df["net_bytes_recv"].iloc[-1] - df["net_bytes_recv"].iloc[0]
            
            summary["network_sent_mbps_avg"] = (sent_diff / time_diff) / (1024 * 1024)
            summary["network_recv_mbps_avg"] = (recv_diff / time_diff) / (1024 * 1024)
        
        return summary
    
    def _process_cli_data(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Process CLI collector data.
        
        Args:
            df: DataFrame with CLI metrics
            
        Returns:
            Dictionary of aggregated metrics
        """
        summary = {}
        
        # Process available CLI tool outputs
        # This is a placeholder - actual implementation would depend on
        # the specific CLI tools and their parsed output format
        
        # Example: vmstat metrics
        if "r" in df.columns:  # Running processes
            summary["processes_running_avg"] = df["r"].mean()
        
        if "b" in df.columns:  # Blocked processes
            summary["processes_blocked_avg"] = df["b"].mean()
        
        if "si" in df.columns:  # Swap in
            summary["swap_in_kbps_avg"] = df["si"].mean()
        
        if "so" in df.columns:  # Swap out
            summary["swap_out_kbps_avg"] = df["so"].mean()
        
        return summary
    
    def _process_perf_data(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Process Perf collector data.
        
        Args:
            df: DataFrame with Perf metrics
            
        Returns:
            Dictionary of aggregated metrics
        """
        summary = {}
        
        # Process perf event counters
        for event in ["cpu-cycles", "instructions", "cache-references", 
                     "cache-misses", "branches", "branch-misses"]:
            if event in df.columns:
                summary[f"perf_{event.replace('-', '_')}_total"] = df[event].sum()
                summary[f"perf_{event.replace('-', '_')}_avg"] = df[event].mean()
        
        # Calculate derived metrics
        if "instructions" in df.columns and "cpu-cycles" in df.columns:
            # Instructions per cycle
            ipc = df["instructions"] / df["cpu-cycles"].replace(0, 1)
            summary["perf_ipc_avg"] = ipc.mean()
        
        if "cache-misses" in df.columns and "cache-references" in df.columns:
            # Cache miss rate
            miss_rate = df["cache-misses"] / df["cache-references"].replace(0, 1)
            summary["perf_cache_miss_rate_avg"] = miss_rate.mean() * 100
        
        return summary
    
    def _process_ebpf_data(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Process eBPF collector data.
        
        Args:
            df: DataFrame with eBPF metrics
            
        Returns:
            Dictionary of aggregated metrics
        """
        summary = {}
        
        # Process eBPF metrics
        if "process_execs" in df.columns:
            summary["ebpf_process_execs_total"] = df["process_execs"].sum()
        
        if "block_io_ops" in df.columns:
            summary["ebpf_block_io_ops_total"] = df["block_io_ops"].sum()
        
        if "tcp_connections" in df.columns:
            summary["ebpf_tcp_connections_total"] = df["tcp_connections"].sum()
        
        return summary
    
    def merge_time_series(
        self,
        dataframes: List[pd.DataFrame],
        method: str = "nearest"
    ) -> pd.DataFrame:
        """
        Merge multiple time series DataFrames.
        
        Args:
            dataframes: List of DataFrames to merge
            method: Method for alignment ('nearest', 'forward', 'backward')
            
        Returns:
            Merged DataFrame
        """
        if not dataframes:
            return pd.DataFrame()
        
        if len(dataframes) == 1:
            return dataframes[0]
        
        # Start with the first DataFrame
        merged = dataframes[0].copy()
        
        # Merge remaining DataFrames
        for df in dataframes[1:]:
            # Align timestamps using the specified method
            if method == "nearest":
                merged = pd.merge_asof(
                    merged.sort_index(),
                    df.sort_index(),
                    left_index=True,
                    right_index=True,
                    direction="nearest"
                )
            else:
                # Simple join for other methods
                merged = merged.join(df, how="outer", rsuffix="_dup")
                
                # Remove duplicate columns
                dup_cols = [col for col in merged.columns if col.endswith("_dup")]
                merged.drop(columns=dup_cols, inplace=True)
        
        return merged
    
    def calculate_statistics(
        self,
        df: pd.DataFrame,
        percentiles: List[float] = [0.5, 0.95, 0.99]
    ) -> pd.DataFrame:
        """
        Calculate statistics for numeric columns in a DataFrame.
        
        Args:
            df: Input DataFrame
            percentiles: List of percentiles to calculate
            
        Returns:
            DataFrame with statistics
        """
        numeric_df = df.select_dtypes(include=[np.number])
        
        stats = {
            "mean": numeric_df.mean(),
            "std": numeric_df.std(),
            "min": numeric_df.min(),
            "max": numeric_df.max(),
        }
        
        # Add percentiles
        for p in percentiles:
            stats[f"p{int(p*100)}"] = numeric_df.quantile(p)
        
        return pd.DataFrame(stats)
