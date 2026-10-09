"""The unified tables of an experiment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from lb_analytics.unify.report import LoadReport

TABLES = ("runs", "host_info", "repetitions", "results", "samples")


@dataclass
class ExperimentData:
    runs: pd.DataFrame
    host_info: pd.DataFrame
    repetitions: pd.DataFrame
    results: pd.DataFrame
    samples: pd.DataFrame
    report: LoadReport

    @property
    def is_empty(self) -> bool:
        return self.results.empty and self.samples.empty

    def to_parquet(self, out_dir: Path) -> list[Path]:
        """Write one Parquet file per table plus ``load_report.json``."""
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for name in TABLES:
            path = out_dir / f"{name}.parquet"
            getattr(self, name).to_parquet(path, index=False)
            paths.append(path)
        report_path = out_dir / "load_report.json"
        report_path.write_text(json.dumps(self.report.to_dict(), indent=2))
        paths.append(report_path)
        return paths
