"""Unify an experiment's datasets into Parquet tables, for every UI."""

from __future__ import annotations

import importlib.util
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lb_analytics.api import ExperimentData, load_experiment
from lb_common.api import ExperimentInfo
from lb_controller.api import RunCatalogService

MAX_SUMMARY_ERRORS = 10


class UnificationError(Exception):
    """A user-facing reason the unification cannot go ahead."""


@dataclass(frozen=True)
class UnificationPreview:
    """What a unification will write, loaded once and shown before writing."""

    experiment: ExperimentInfo
    data: ExperimentData
    hosts: tuple[str, ...]
    workloads: tuple[str, ...]
    out_dir: Path
    command: str

    @property
    def row_counts(self) -> dict[str, int]:
        return self.data.row_counts

    @property
    def is_empty(self) -> bool:
        return self.data.is_empty

    @property
    def empty_reason(self) -> str:
        filtered = " after the filters" if self.hosts or self.workloads else ""
        return f"no results or samples{filtered}"

    def summary_rows(self) -> list[tuple[str, str]]:
        """Label/value pairs every UI shows before the user confirms."""
        report = self.data.report
        hosts = self.hosts or self.experiment.hosts
        workloads = self.workloads or self.experiment.workloads
        rows = [
            ("Experiment", self.experiment.id),
            ("Kind", self.experiment.kind),
            ("Runs", str(len(self.experiment.runs))),
            ("Hosts", ", ".join(hosts) or "-"),
            ("Workloads", ", ".join(workloads) or "-"),
        ]
        rows += [(f"Rows: {name}", str(n)) for name, n in self.row_counts.items()]
        rows += [
            ("Failed repetitions", str(len(report.failed_repetitions))),
            ("Load errors", str(len(report.errors))),
            ("Load warnings", str(len(report.warnings))),
        ]
        shown = report.errors[:MAX_SUMMARY_ERRORS]
        rows += [(f"Error: {e['source']}", e["message"]) for e in shown]
        hidden = len(report.errors) - len(shown)
        if hidden:
            rows.append(("More errors", f"{hidden} more in load_report.json"))
        if self.is_empty:
            rows.append(("Nothing to unify", self.empty_reason))
        rows.append(("Output", str(self.out_dir)))
        return rows


class UnificationService:
    """List experiments, preview their unification, write it."""

    def __init__(
        self,
        catalog: RunCatalogService,
        export_root: Path,
        config_path: Path | None = None,
    ) -> None:
        self._catalog = catalog
        # Absolute, so the printed output folder means the same from anywhere.
        self._export_root = export_root.resolve()
        self._config_path = config_path

    @property
    def output_dir(self) -> Path:
        return self._catalog.output_dir

    def list_targets(self) -> list[ExperimentInfo]:
        """Experiments newest first, then the whole folder; [] without runs."""
        experiments = self._catalog.list_experiments()
        if not experiments:
            return []
        return [*experiments, self._catalog.folder_experiment()]

    def find(self, experiment_id: str | None) -> ExperimentInfo:
        """The named experiment, or the whole folder for ``None``."""
        if experiment_id is None:
            folder = self._catalog.folder_experiment()
            if not folder.runs:
                raise UnificationError(f"No runs in {self.output_dir}")
            return folder
        found = self._catalog.get_experiment(experiment_id)
        if found is None:
            recent = [e.id for e in self._catalog.list_experiments()[:5]]
            hint = f"; recent experiments: {', '.join(recent)}" if recent else ""
            raise UnificationError(
                f"Experiment {experiment_id!r} not found in {self.output_dir}{hint}"
            )
        return found

    def prepare(
        self,
        experiment: ExperimentInfo,
        hosts: Sequence[str] = (),
        workloads: Sequence[str] = (),
    ) -> UnificationPreview:
        """Load and filter the experiment; nothing is written yet."""
        if not _has_pyarrow():
            raise UnificationError(
                "Writing Parquet needs pyarrow: "
                "pip install 'linux-benchmark-lib[controller]'"
            )
        _check_names("host", hosts, experiment.hosts)
        _check_names("workload", workloads, experiment.workloads)
        host_filter = _effective(hosts, experiment.hosts)
        workload_filter = _effective(workloads, experiment.workloads)
        data = load_experiment(experiment.runs).filter(host_filter, workload_filter)
        return UnificationPreview(
            experiment=experiment,
            data=data,
            hosts=host_filter,
            workloads=workload_filter,
            out_dir=self._out_dir(experiment),
            command=self._command(experiment, host_filter, workload_filter),
        )

    def write(self, preview: UnificationPreview) -> list[Path]:
        """Write the previewed tables, replacing an earlier unification."""
        if preview.is_empty:
            raise UnificationError(
                f"Nothing to unify for {preview.experiment.id}: {preview.empty_reason}"
            )
        try:
            return preview.data.to_parquet(preview.out_dir)
        except Exception as exc:  # disk, permissions, pyarrow: say why, no traceback
            raise UnificationError(f"Could not write {preview.out_dir}: {exc}") from exc

    def _out_dir(self, experiment: ExperimentInfo) -> Path:
        # Experiment ids start with a letter or digit, so "_folders" can never
        # be one: a folder and an experiment sharing a name stay apart.
        if experiment.kind == "folder":
            return self._export_root / "_folders" / experiment.id
        return self._export_root / experiment.id

    def _command(
        self,
        experiment: ExperimentInfo,
        hosts: Sequence[str],
        workloads: Sequence[str],
    ) -> str:
        args = ["lb", "runs", "analyze"]
        if experiment.kind == "folder":
            args.append("--folder")
        else:
            args += ["--experiment", experiment.id]
        args += ["--root", str(self.output_dir)]
        if self._config_path is not None:
            args += ["--config", str(self._config_path)]
        for host in hosts:
            args += ["--host", host]
        for workload in workloads:
            args += ["--workload", workload]
        return shlex.join(args)


def _effective(selected: Sequence[str], available: Sequence[str]) -> tuple[str, ...]:
    """The filter to apply: empty when everything available is selected."""
    chosen = tuple(sorted(set(selected)))
    return () if set(chosen) >= set(available) else chosen


def _check_names(kind: str, selected: Sequence[str], available: Sequence[str]) -> None:
    """A typo'd filter name is an error, not a silently empty result."""
    unknown = sorted(set(selected) - set(available))
    if unknown:
        raise UnificationError(
            f"Unknown {kind} {unknown[0]!r}; available: {', '.join(available)}"
        )


def _has_pyarrow() -> bool:
    return importlib.util.find_spec("pyarrow") is not None
