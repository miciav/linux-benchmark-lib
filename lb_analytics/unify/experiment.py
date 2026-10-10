"""The unified tables of an experiment."""

from __future__ import annotations

import json
from collections.abc import Sequence
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

    @property
    def row_counts(self) -> dict[str, int]:
        return {name: len(getattr(self, name)) for name in TABLES}

    def filter(
        self, hosts: Sequence[str] = (), workloads: Sequence[str] = ()
    ) -> ExperimentData:
        """Keep the given hosts and workloads; an empty filter keeps everything.

        A filter applies to every table that has its column, so ``runs`` is
        never filtered and ``host_info`` only by host.
        """
        tables: dict[str, pd.DataFrame] = {}
        for name in TABLES:
            frame = getattr(self, name)
            if hosts and "host" in frame.columns:
                frame = frame[frame["host"].isin(hosts)]
            if workloads and "workload" in frame.columns:
                frame = frame[frame["workload"].isin(workloads)]
            tables[name] = frame.reset_index(drop=True)
        return ExperimentData(**tables, report=self.report)

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
