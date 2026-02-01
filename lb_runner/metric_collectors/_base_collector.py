"""
Base collector abstract class for metric collectors.

This module defines the common interface that all metric collectors must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from datetime import datetime
import threading
import time
import logging
from pathlib import Path
import pandas as pd

from lb_common.errors import MetricCollectionError


logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base class for all metric collectors."""
    
    def __init__(self, name: str, interval_seconds: float = 1.0):
        """
        Initialize the base collector.
        
        Args:
            name: Name of the collector
            interval_seconds: Sampling interval in seconds
        """
        self.name = name
        self.interval_seconds = interval_seconds
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._data: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._start_time: Optional[datetime] = None
        self._stop_time: Optional[datetime] = None
        self._errors: list[MetricCollectionError] = []
        
    @abstractmethod
    def _collect_metrics(self) -> Dict[str, Any]:
        """
        Collect metrics at a single point in time.
        
        Returns:
            Dictionary containing metric names and their values
        """
        pass
    
    @abstractmethod
    def _validate_environment(self) -> bool:
        """
        Validate that the collector can run in the current environment.
        
        Returns:
            True if the environment is valid, False otherwise
        """
        pass
    
    def start(self) -> None:
        """Start the metric collection in a background thread."""
        if self._is_running:
            logger.warning(f"{self.name} collector is already running")
            return
            
        if not self._validate_environment():
            raise MetricCollectionError(
                f"{self.name} collector cannot run in this environment",
                context={"collector": self.name},
            )
        
        self._is_running = True
        self._start_time = datetime.now()
        self._data.clear()
        self._errors.clear()
        
        self._thread = threading.Thread(target=self._collection_loop, daemon=True)
        self._thread.start()
        
        logger.info(f"{self.name} collector started")
    
    def stop(self) -> None:
        """Stop the metric collection."""
        if not self._is_running:
            logger.warning(f"{self.name} collector is not running")
            return
        
        self._is_running = False
        self._stop_time = datetime.now()
        
        if self._thread:
            self._thread.join(timeout=self.interval_seconds * 2)
            
        logger.info(f"{self.name} collector stopped")
    
    def _collection_loop(self) -> None:
        """Main collection loop that runs in a background thread."""
        while self._is_running:
            try:
                start = time.time()
                
                # Collect metrics
                metrics = self._collect_metrics()
                
                # Add timestamp and collector info
                metrics["timestamp"] = datetime.now().isoformat()
                metrics["collector"] = self.name
                
                # Store data thread-safely
                with self._lock:
                    self._data.append(metrics)
                
                # Sleep for the remaining interval time
                elapsed = time.time() - start
                sleep_time = max(0, self.interval_seconds - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    
            except Exception as e:
                error = MetricCollectionError(
                    f"{self.name} collector failed to collect metrics",
                    context={"collector": self.name},
                    cause=e,
                )
                self._errors.append(error)
                logger.error(
                    "Error in %s collector: %s", self.name, e, exc_info=True
                )
                # Continue collecting even on error
    
    def get_data(self) -> List[Dict[str, Any]]:
        """
        Get the collected data.
        
        Returns:
            List of dictionaries containing metric data
        """
        with self._lock:
            return self._data.copy()

    def get_errors(self) -> list[MetricCollectionError]:
        """Return collected metric errors, if any."""
        return list(self._errors)
    
    def get_dataframe(self) -> pd.DataFrame:
        """
        Get the collected data as a pandas DataFrame.
        
        Returns:
            DataFrame with metrics data
        """
        data = self.get_data()
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df.set_index("timestamp", inplace=True)
        
        return df
    
    def save_data(self, filepath: Path, format: str = "csv") -> None:
        """
        Save collected data to file.
        
        Args:
            filepath: Path to save the data
            format: Format to save in ('csv', 'json', 'parquet')
        """
        df = self.get_dataframe()
        
        if format == "csv":
            df.to_csv(filepath)
        elif format == "json":
            df.to_json(filepath, orient="records", date_format="iso")
        elif format == "parquet":
            df.to_parquet(filepath)
        else:
            raise ValueError(f"Unsupported format: {format}")
            
        logger.info(f"Saved {self.name} data to {filepath}")
    
    def clear_data(self) -> None:
        """Clear all collected data."""
        with self._lock:
            self._data.clear()
    
    def get_summary_stats(self) -> Dict[str, Dict[str, float]]:
        """
        Get summary statistics for all numeric metrics.
        
        Returns:
            Dictionary mapping metric names to their statistics
        """
        df = self.get_dataframe()
        if df.empty:
            return {}
        
        # Select only numeric columns
        numeric_df = df.select_dtypes(include=['number'])
        
        stats = {}
        for col in numeric_df.columns:
            stats[col] = {
                "mean": numeric_df[col].mean(),
                "std": numeric_df[col].std(),
                "min": numeric_df[col].min(),
                "max": numeric_df[col].max(),
                "median": numeric_df[col].median(),
                "p95": numeric_df[col].quantile(0.95),
                "p99": numeric_df[col].quantile(0.99),
            }
        
        return stats
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, *_args):
        """Context manager exit."""
        self.stop()
