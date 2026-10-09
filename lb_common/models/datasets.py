"""Dataset manifests: how producers declare the tables they write.

Workload plugins and the runner write a ``datasets.json`` next to their files;
``lb_analytics`` reads only these manifests. This module is the shared contract,
including the column planning both the loader and the plugin contract tests use.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MANIFEST_FILENAME = "datasets.json"

Shape = Literal["wide", "long", "timeseries"]
TargetTable = Literal["results", "samples", "host_info", "ignore"]


class MetricSpec(BaseModel):
    """One metric of a wide dataset: an exact column or a regex over columns."""

    model_config = ConfigDict(extra="forbid")

    column: str | None = None
    pattern: str | None = None
    name: str | None = None
    unit: str | None = None
    unit_column: str | None = None

    @model_validator(mode="after")
    def _check(self) -> MetricSpec:
        if (self.column is None) == (self.pattern is None):
            raise ValueError("a metric needs exactly one of 'column' or 'pattern'")
        if self.pattern is not None:
            if "metric" not in re.compile(self.pattern).groupindex:
                raise ValueError(f"pattern {self.pattern!r} needs a 'metric' group")
            if self.name is not None:
                raise ValueError("'name' applies to 'column' metrics only")
        if self.unit is not None and self.unit_column is not None:
            raise ValueError("use 'unit' or 'unit_column', not both")
        return self


class ValueColumn(BaseModel):
    """A measure column of a long dataset; the metric name is the column name."""

    model_config = ConfigDict(extra="forbid")

    column: str
    unit: str | None = None


class DatasetDescriptor(BaseModel):
    """Declaration of one dataset file (or glob of files)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    shape: Shape
    table: TargetTable | None = None
    keys: list[str] = Field(default_factory=list)
    fixed: dict[str, str | int] = Field(default_factory=dict)
    metrics: list[MetricSpec] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    value_columns: list[ValueColumn] = Field(default_factory=list)
    metric_column: str | None = None
    value_column: str | None = None
    unit: str | None = None
    unit_column: str | None = None
    time_column: str | None = None

    @property
    def target_table(self) -> TargetTable:
        if self.table is not None:
            return self.table
        return "samples" if self.shape == "timeseries" else "results"

    @model_validator(mode="after")
    def _check_shape(self) -> DatasetDescriptor:
        for pattern in self.exclude:
            re.compile(pattern)
        named = {*self.keys, *self.fixed}
        for spec in self.metrics:
            if spec.pattern is None:
                continue
            clash = named & (set(re.compile(spec.pattern).groupindex) - {"metric"})
            if clash:
                raise ValueError(
                    f"{self.name}: {sorted(clash)} is both a key and a pattern "
                    "dimension"
                )
        if self.shape == "timeseries" and not self.time_column:
            raise ValueError(f"{self.name}: a timeseries needs 'time_column'")
        if self.shape == "long" and self.target_table == "host_info":
            if not self.value_column:
                raise ValueError(f"{self.name}: host_info needs 'value_column'")
        elif self.shape == "long" and self.target_table != "ignore":
            pair = self.metric_column is not None and self.value_column is not None
            if bool(self.value_columns) == pair:
                raise ValueError(
                    f"{self.name}: a long dataset needs 'value_columns' or "
                    "'metric_column' + 'value_column'"
                )
        return self


class DatasetManifest(BaseModel):
    """Content of one ``datasets.json``."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    workload: str | None = None
    plugin: str | None = None
    repetitions: str | None = None
    datasets: list[DatasetDescriptor] = Field(default_factory=list)


def write_manifest(directory: Path, manifest: DatasetManifest) -> Path:
    """Write ``datasets.json`` into ``directory`` and return its path."""
    path = directory / MANIFEST_FILENAME
    path.write_text(manifest.model_dump_json(indent=2, exclude_none=True))
    return path


def read_manifest(directory: Path) -> DatasetManifest:
    """Read and validate ``directory/datasets.json``."""
    text = (directory / MANIFEST_FILENAME).read_text()
    return DatasetManifest.model_validate_json(text)


@dataclass(frozen=True)
class MetricColumn:
    """A wide column resolved to a metric, its dimensions and its unit."""

    column: str
    metric: str
    dims: dict[str, str]
    unit: str | None
    unit_column: str | None


@dataclass
class WidePlan:
    """How the columns of a wide file map onto metrics."""

    metrics: list[MetricColumn] = field(default_factory=list)
    unmatched_specs: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


def plan_wide(descriptor: DatasetDescriptor, columns: Sequence[str]) -> WidePlan:
    """Resolve which columns of a wide file are metrics, and how."""
    excluded = [re.compile(p) for p in descriptor.exclude]
    keys = {*descriptor.keys, "repetition"}

    def available(column: str) -> bool:
        return column not in keys and not any(p.fullmatch(column) for p in excluded)

    plan = WidePlan()
    claimed: set[str] = set()
    for spec in descriptor.metrics:
        matched = False
        for column in columns:
            if column in claimed or not available(column):
                continue
            resolved = _resolve(spec, column)
            if resolved is not None:
                plan.metrics.append(resolved)
                claimed.add(column)
                matched = True
        if not matched:
            plan.unmatched_specs.append(spec.column or spec.pattern or "")
    plan.ignored = [c for c in columns if c not in claimed and available(c)]
    return plan


def _resolve(spec: MetricSpec, column: str) -> MetricColumn | None:
    if spec.column is not None:
        if column != spec.column:
            return None
        return MetricColumn(
            column, spec.name or column, {}, spec.unit, spec.unit_column
        )
    assert spec.pattern is not None
    match = re.fullmatch(spec.pattern, column)
    if match is None:
        return None
    groups = {k: v for k, v in match.groupdict().items() if v is not None}
    metric = groups.pop("metric")
    unit_column = spec.unit_column.format(**groups) if spec.unit_column else None
    return MetricColumn(column, metric, groups, spec.unit, unit_column)
