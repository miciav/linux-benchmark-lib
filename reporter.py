"""
Reporter module for generating benchmark reports and visualizations.

This module creates textual and graphical reports from aggregated benchmark data.
"""

import logging
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict


logger = logging.getLogger(__name__)


class Reporter:
    """Reporter for generating and exporting benchmark reports."""
    
    def __init__(self, output_dir: Path):
        """
        Initialize the reporter.
        
        Args:
            output_dir: Directory for saving report files
        """
        self.output_dir = output_dir

    def generate_text_report(
        self,
        aggregated_df: pd.DataFrame,
        test_name: str
    ) -> None:
        """
        Generate a textual report for a benchmark test.
        
        Args:
            aggregated_df: DataFrame containing aggregated benchmark data
            test_name: Name of the test
        """
        logger.info(f"Generating textual report for {test_name}")

        report_path = self.output_dir / f"{test_name}_report.txt"

        # Write summary statistics
        with open(report_path, "w") as f:
            f.write(f"Benchmark Report: {test_name}\n\n")
            f.write(f"{'Metric':<30} {'Mean':>10} {'Std Dev':>10} {'Min':>10} {'Max':>10} {'p95':>10}\n")
            f.write(f"{'-' * 80}\n")
            
            stats = aggregated_df.describe(percentiles=[0.95]).transpose()
            
            for metric, stat_row in stats.iterrows():
                f.write(f"{metric:<30} {stat_row['mean']:>10.2f} {stat_row['std']:>10.2f} {stat_row['min']:>10.2f} {stat_row['max']:>10.2f} {stat_row['95%']:>10.2f}\n")
        
        logger.info(f"Textual report written to {report_path}")

    def generate_graphical_report(
        self,
        aggregated_df: pd.DataFrame,
        test_name: str
    ) -> None:
        """
        Generate graphical report for a benchmark test.
        
        Args:
            aggregated_df: DataFrame containing aggregated benchmark data
            test_name: Name of the test
        """
        logger.info(f"Generating graphical report for {test_name}")

        plt.figure(figsize=(12, 8))
        sns.boxplot(data=aggregated_df.transpose())
        plt.title(f"Distribution of Metrics for {test_name}")
        plt.xticks(rotation=45)
        graph_file = self.output_dir / f"{test_name}_boxplot.png"
        plt.savefig(graph_file, bbox_inches="tight")
        plt.close()

        logger.info(f"Graphical report saved as {graph_file}")

    def save_to_csv(
        self,
        aggregated_df: pd.DataFrame,
        test_name: str
    ) -> None:
        """
        Save aggregated benchmark data to CSV.
        
        Args:
            aggregated_df: DataFrame containing aggregated benchmark data
            test_name: Name of the test
        """
        csv_path = self.output_dir / f"{test_name}_summary.csv"
        aggregated_df.to_csv(csv_path)
        logger.info(f"Aggregated data saved to CSV at {csv_path}")
