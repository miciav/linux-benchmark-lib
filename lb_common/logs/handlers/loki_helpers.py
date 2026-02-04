"""Helper classes for Loki handler internals."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from lb_common.logs.handlers.loki_types import LokiLogEntry


@dataclass(frozen=True)
class LokiLabelBuilder:
    """Build Loki labels from handler defaults and log records."""

    component: str
    host: str
    run_id: str
    workload: str | None
    package: str | None
    plugin: str | None
    scenario: str | None
    repetition: int | None
    labels: Mapping[str, str]

    def build(self, record: logging.LogRecord) -> dict[str, str]:
        labels: dict[str, str] = {}
        _add_label_if_value(labels, "component", self.component)
        _add_label_if_value(labels, "host", self.host)
        _add_label_if_value(labels, "run_id", self.run_id)
        _add_label_if_value(labels, "workload", self.workload)
        _add_label_if_value(labels, "package", self.package)
        _add_label_if_value(labels, "plugin", self.plugin)
        _add_label_if_value(labels, "scenario", self.scenario)
        _add_label_if_not_none(labels, "repetition", self.repetition)

        _merge_record_labels(labels, record)
        _merge_phase_label(labels, record)
        _merge_static_labels(labels, self.labels)
        _apply_label_overrides(labels, record)

        return labels


@dataclass
class LokiWorker:
    """Background worker that batches and flushes Loki entries."""

    queue: queue.Queue
    stop_event: threading.Event
    push_entries: Callable[[list["LokiLogEntry"]], None]
    batch_size: int = 100
    flush_interval: float = 1.0

    def run(self) -> None:
        pending: list[LokiLogEntry] = []
        next_flush = time.monotonic() + self.flush_interval
        while not self.stop_event.is_set() or not self.queue.empty() or pending:
            timeout = max(0.0, next_flush - time.monotonic())
            entry = self._get_entry(timeout)
            if entry and (entry.line or entry.labels):
                pending.append(entry)

            next_flush = self._flush_if_ready(pending, next_flush)

        if pending:
            self.push_entries(pending)

    def _get_entry(self, timeout: float) -> LokiLogEntry | None:
        try:
            entry = self.queue.get(timeout=timeout)
        except queue.Empty:
            return None
        self.queue.task_done()
        return entry

    def _flush_if_ready(self, pending: list[LokiLogEntry], next_flush: float) -> float:
        now = time.monotonic()
        if pending and (len(pending) >= self.batch_size or now >= next_flush):
            self.push_entries(pending)
            pending.clear()
            return now + self.flush_interval
        return next_flush


def _add_label_if_value(labels: dict[str, str], key: str, value: object) -> None:
    if value:
        labels[key] = str(value)


def _add_label_if_not_none(labels: dict[str, str], key: str, value: object) -> None:
    if value is not None:
        labels[key] = str(value)


def _merge_record_labels(labels: dict[str, str], record: logging.LogRecord) -> None:
    record_labels = getattr(record, "lb_labels", None)
    if isinstance(record_labels, Mapping):
        for key, value in record_labels.items():
            if value is None:
                continue
            labels[str(key)] = str(value)


def _merge_phase_label(labels: dict[str, str], record: logging.LogRecord) -> None:
    phase = getattr(record, "lb_phase", None)
    if phase is not None:
        labels["phase"] = str(phase)


def _merge_static_labels(
    labels: dict[str, str], static_labels: Mapping[str, str]
) -> None:
    for key, value in static_labels.items():
        if value is None:
            continue
        labels[str(key)] = str(value)


def _apply_label_overrides(labels: dict[str, str], record: logging.LogRecord) -> None:
    overrides = {
        "component": getattr(record, "lb_component", None),
        "host": getattr(record, "lb_host", None),
        "run_id": getattr(record, "lb_run_id", None),
        "workload": getattr(record, "lb_workload", None),
        "package": getattr(record, "lb_package", None),
        "plugin": getattr(record, "lb_plugin", None),
        "scenario": getattr(record, "lb_scenario", None),
        "repetition": getattr(record, "lb_repetition", None),
    }
    for key, value in overrides.items():
        if value is not None:
            labels[key] = str(value)
