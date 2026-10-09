"""Write the datasets.json manifests that lb_analytics loads."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from lb_common.api import DatasetDescriptor, DatasetManifest, write_manifest
from lb_plugins.api import WorkloadPlugin

logger = logging.getLogger(__name__)

# Collector files are named <test>_rep<N>_<Collector>.csv by collect_metrics().
_COLLECTOR_FILE = re.compile(r"^(?P<test>.+)_rep(?P<rep>\d+)_(?P<collector>.+)\.csv$")

SYSTEM_INFO_DATASET = DatasetDescriptor(
    name="system_info",
    path="system_info.csv",
    shape="long",
    table="host_info",
    keys=["category", "name"],
    value_column="value",
)


def collector_datasets(workload_dir: Path, test_name: str) -> list[DatasetDescriptor]:
    """One timeseries descriptor per collector CSV under ``rep*/``."""
    datasets = []
    for path in sorted(workload_dir.glob("rep*/*.csv")):
        match = _COLLECTOR_FILE.match(path.name)
        if match is None or match["test"] != test_name:
            continue
        datasets.append(
            DatasetDescriptor(
                name=path.stem,
                path=path.relative_to(workload_dir).as_posix(),
                shape="timeseries",
                time_column="timestamp",
                # Wall-clock and uptime fields describe when, not how the host
                # performed; they are noise as performance samples.
                exclude=[r"time_.*", r"uptime_.*"],
                fixed={
                    "repetition": int(match["rep"]),
                    "collector": match["collector"],
                },
            )
        )
    return datasets


def write_workload_manifest(
    plugin: WorkloadPlugin | None, workload_dir: Path, test_name: str
) -> Path:
    """Write ``<workload_dir>/datasets.json``: plugin datasets plus collectors."""
    datasets: list[DatasetDescriptor] = []
    if plugin is not None:
        try:
            datasets.extend(plugin.describe_datasets(workload_dir, test_name))
        except Exception as exc:
            logger.warning("Plugin '%s' describe_datasets failed: %s", plugin.name, exc)
    datasets.extend(collector_datasets(workload_dir, test_name))
    manifest = DatasetManifest(
        workload=test_name,
        plugin=plugin.name if plugin is not None else None,
        repetitions=f"{test_name}_results.json",
        datasets=datasets,
    )
    return write_manifest(workload_dir, manifest)


def write_host_manifest(host_dir: Path) -> Path:
    """Write ``<host_dir>/datasets.json`` declaring ``system_info.csv``."""
    return write_manifest(host_dir, DatasetManifest(datasets=[SYSTEM_INFO_DATASET]))
