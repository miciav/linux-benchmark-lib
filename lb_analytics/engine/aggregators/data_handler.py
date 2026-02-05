"""
Data handler module for processing and aggregating benchmark data.

This module is responsible for transforming raw metric data into aggregated
DataFrames suitable for analysis and reporting.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TypedDict

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
        # Fallback to built-in aggregators so legacy callers still work when no
        # registry is passed.
        if not self.collector_aggregators:
            self.collector_aggregators.update(
                {
                    "PSUtilCollector": aggregate_psutil,
                    "CLICollector": aggregate_cli,
                }
            )

    @staticmethod
    def _parse_time(value: Optional[str]) -> Optional[pd.Timestamp]:
        if not value:
            return None
        return pd.to_datetime(value)

    @staticmethod
    def _filter_by_time(
        df: pd.DataFrame,
        start_time: Optional[pd.Timestamp],
        end_time: Optional[pd.Timestamp],
    ) -> pd.DataFrame:
        if start_time and end_time:
            return df[(df["timestamp"] >= start_time) & (df["timestamp"] <= end_time)]
        return df

    def _normalize_collector_df(
        self,
        collector_name: str,
        collector_data: List[Dict[str, Any]],
        start_time: Optional[pd.Timestamp],
        end_time: Optional[pd.Timestamp],
    ) -> Optional[pd.DataFrame]:
        if not collector_data:
            return None

        df = pd.DataFrame(collector_data)
        if "timestamp" not in df.columns:
            return df

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = self._filter_by_time(df, start_time, end_time)
        if df.empty:
            logger.warning(
                "Collector %s has no data after filtering by test duration",
                collector_name,
            )
            return None

        df.set_index("timestamp", inplace=True)
        return df

    def _aggregate_collector(
        self, collector_name: str, df: pd.DataFrame
    ) -> Dict[str, Any]:
        aggregator = self.collector_aggregators.get(collector_name)
        if not callable(aggregator):
            logger.warning(
                "No aggregator registered for collector '%s'; skipping.",
                collector_name,
            )
            return {}
        try:
            return aggregator(df)
        except Exception as exc:
            logger.error(
                "Aggregation failed for collector '%s': %s",
                collector_name,
                exc,
            )
            return {}

    def _build_repetition_summary(
        self, result: TestResult
    ) -> Dict[str, Dict[str, Any]]:
        rep_num = result["repetition"]
        metrics = result["metrics"]
        start_time = self._parse_time(result.get("start_time"))
        end_time = self._parse_time(result.get("end_time"))

        rep_summary: Dict[str, Any] = {}
        for collector_name, collector_data in metrics.items():
            df = self._normalize_collector_df(
                collector_name, collector_data, start_time, end_time
            )
            if df is None:
                continue
            rep_summary.update(self._aggregate_collector(collector_name, df))

        return {f"Repetition_{rep_num}": rep_summary}

    def process_test_results(
        self,
        test_name: str,
        results: List[TestResult],
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

        repetition_summaries = [
            self._build_repetition_summary(result) for result in results
        ]

        # Create final DataFrame with metrics as index and repetitions as columns
        if not repetition_summaries:
            return None

        # Combine all repetition data
        combined_data: Dict[str, Dict[str, Any]] = {}
        for rep_dict in repetition_summaries:
            for rep_name, metrics in rep_dict.items():
                combined_data[rep_name] = metrics

        # Create DataFrame and transpose so metrics are index
        df = pd.DataFrame(combined_data).T
        final_df = df.T  # Transpose so metrics are rows

        # Sort index (metric names)
        final_df.sort_index(inplace=True)

        logger.info(
            "Created aggregated DataFrame for %s with shape %s",
            test_name,
            final_df.shape,
        )

        return final_df
