"""Helpers for plugins declaring their exported datasets."""

from __future__ import annotations

from collections.abc import Sequence

from lb_common.api import DatasetDescriptor, MetricSpec

# Columns every plugin CSV carries that are not measurements: identity,
# repetition status (it lives in the repetitions table) and raw output.
STANDARD_EXCLUDES: tuple[str, ...] = (
    "run_id",
    "workload",
    "success",
    "duration_seconds",
    "returncode",
    "max_retries",
    "tags",
    "generator_stdout",
    "generator_stderr",
    "generator_command",
    "generator_returncode",
    "generator_max_retries",
    "generator_tags",
)


def plugin_csv_dataset(
    test_name: str,
    *,
    metrics: Sequence[MetricSpec],
    keys: Sequence[str] = (),
    exclude: Sequence[str] = (),
    suffix: str = "plugin",
) -> DatasetDescriptor:
    """Describe the wide ``<test_name>_<suffix>.csv`` a plugin exports."""
    return DatasetDescriptor(
        name=f"{test_name}_{suffix}",
        path=f"{test_name}_{suffix}.csv",
        shape="wide",
        keys=list(keys),
        metrics=list(metrics),
        exclude=[*STANDARD_EXCLUDES, *exclude],
    )
