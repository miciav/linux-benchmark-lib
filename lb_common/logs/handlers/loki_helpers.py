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
        if self.component:
            labels["component"] = str(self.component)
        if self.host:
            labels["host"] = str(self.host)
        if self.run_id:
            labels["run_id"] = str(self.run_id)
        if self.workload:
            labels["workload"] = str(self.workload)
        if self.package:
            labels["package"] = str(self.package)
        if self.plugin:
            labels["plugin"] = str(self.plugin)
        if self.scenario:
            labels["scenario"] = str(self.scenario)
        if self.repetition is not None:
            labels["repetition"] = str(self.repetition)

        record_labels = getattr(record, "lb_labels", None)
        if isinstance(record_labels, Mapping):
            for key, value in record_labels.items():
                if value is None:
                    continue
                labels[str(key)] = str(value)

        phase = getattr(record, "lb_phase", None)
        if phase is not None:
            labels["phase"] = str(phase)

        for key, value in self.labels.items():
            if value is None:
                continue
            labels[str(key)] = str(value)

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
            try:
                entry = self.queue.get(timeout=timeout)
                if entry.line or entry.labels:
                    pending.append(entry)
                self.queue.task_done()
            except queue.Empty:
                pass

            now = time.monotonic()
            if pending and (len(pending) >= self.batch_size or now >= next_flush):
                self.push_entries(pending)
                pending = []
                next_flush = now + self.flush_interval

        if pending:
            self.push_entries(pending)
