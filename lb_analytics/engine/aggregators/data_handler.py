"""
Data handler module for processing and aggregating benchmark data.

This module is responsible for transforming raw metric data into aggregated
DataFrames suitable for analysis and reporting.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

import numpy as np
import pandas as pd

from lb_analytics.engine.aggregators.collectors import (
    aggregate_cli,
    aggregate_psutil,
)

logger = logging.getLogger(__name__)


class TestResult(TypedDict):
    """Structure of a single test repetition result."""
    repetition: int
    metrics: Dict[str, List[Dict[str, Any]]]
    start_time: Optional[str]
    end_time: Optional[str]


class DataHandler:
    """Handler for processing and aggregating benchmark data."""
    
    def __init__(self, collectors: Optional[Dict[str, Any]] = None):
        """
        Initialize the data handler.

        Args:
            collectors: Optional mapping of collector name to CollectorPlugin metadata.
                        Used to look up aggregator functions supplied by collectors.
        """
        collectors = collectors or {}
        self.collector_aggregators: Dict[str, Any] = {
            name: plugin.aggregator
            for name, plugin in collectors.items()
            if getattr(plugin, "aggregator", None)
        }
        # Fallback to built-in aggregators so legacy callers still work when no registry is passed
        if not self.collector_aggregators:
            self.collector_aggregators.update(
                {
                    "PSUtilCollector": aggregate_psutil,
                    "CLICollector": aggregate_cli,
                }
            )
    
    def process_test_results(
        self,
        test_name: str,
        results: List[TestResult]
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
            
            # Parse test start/end times
            start_time = pd.to_datetime(result["start_time"]) if result.get("start_time") else None
            end_time = pd.to_datetime(result["end_time"]) if result.get("end_time") else None
            
            # Extract and aggregate metrics from each collector
            rep_summary = {}
            
            for collector_name, collector_data in metrics.items():
                if not collector_data:
                    continue

                df = pd.DataFrame(collector_data)

                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])

                    if start_time and end_time:
                        df = df[
                            (df["timestamp"] >= start_time) &
                            (df["timestamp"] <= end_time)
                        ]

                    if df.empty:
                        logger.warning(f"Collector {collector_name} has no data after filtering by test duration")
                        continue

                    df.set_index("timestamp", inplace=True)

                aggregator = self.collector_aggregators.get(collector_name)
                if not callable(aggregator):
                    logger.warning("No aggregator registered for collector '%s'; skipping.", collector_name)
                    continue
                try:
                    rep_summary.update(aggregator(df))
                except Exception as exc:
                    logger.error("Aggregation failed for collector '%s': %s", collector_name, exc)
            
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
