"""Loki push handler for non-blocking log shipping."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Mapping, Any
from urllib import request, error

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LokiLogEntry:
    """Normalized Loki log entry payload."""

    labels: Mapping[str, str]
    timestamp_ns: str
    line: str


def normalize_loki_endpoint(endpoint: str) -> str:
    """Return a Loki push URL (ending with /loki/api/v1/push)."""
    trimmed = endpoint.rstrip("/")
    if trimmed.endswith("/loki/api/v1/push"):
        return trimmed
    return f"{trimmed}/loki/api/v1/push"


def build_loki_payload(entries: Iterable[LokiLogEntry]) -> dict[str, Any]:
    """Build Loki push payload grouped by stream labels."""
    streams: dict[tuple[tuple[str, str], ...], list[list[str]]] = {}
    for entry in entries:
        key = tuple(sorted(entry.labels.items()))
        streams.setdefault(key, []).append([entry.timestamp_ns, entry.line])
    return {
        "streams": [
            {"stream": dict(labels), "values": values}
            for labels, values in streams.items()
        ]
    }


class LokiPushHandler(logging.Handler):
    """Logging handler that ships formatted records to Loki in the background."""

    def __init__(
        self,
        *,
        endpoint: str,
        component: str,
        host: str,
        run_id: str,
        workload: str | None = None,
        package: str | None = None,
        plugin: str | None = None,
        scenario: str | None = None,
        repetition: int | None = None,
        labels: Mapping[str, str] | None = None,
        batch_size: int = 100,
        flush_interval: float = 1.0,
        timeout_seconds: float = 5.0,
        max_retries: int = 3,
        max_queue_size: int = 10000,
        backoff_base: float = 0.5,
        backoff_factor: float = 2.0,
    ) -> None:
        super().__init__()
        self._endpoint = normalize_loki_endpoint(endpoint)
        self._component = component
        self._host = host
        self._run_id = run_id
        self._workload = workload
        self._package = package
        self._plugin = plugin
        self._scenario = scenario
        self._repetition = repetition
        self._labels = dict(labels or {})
        self._batch_size = max(1, batch_size)
        self._flush_interval = max(0.1, flush_interval)
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._max_queue_size = max(1, max_queue_size)
        self._backoff_base = max(0.0, backoff_base)
        self._backoff_factor = max(1.0, backoff_factor)
        self._queue: queue.Queue[LokiLogEntry] = queue.Queue(
            maxsize=self._max_queue_size
        )
        self._stop_event = threading.Event()
        self._worker = threading.Thread(
            target=self._run_worker,
            name="loki-push-handler",
            daemon=True,
        )
        self._worker.start()

    def emit(self, record: logging.LogRecord) -> None:
        """Enqueue a log record for async push."""
        try:
            entry = self._build_entry(record)
            if entry is None:
                return
            self._queue.put_nowait(entry)
        except queue.Full:
            _logger.debug("Loki handler queue full, dropping log entry")
            return
        except Exception as exc:
            _logger.debug("Loki handler emit error: %s", exc)
            return

    def close(self) -> None:
        """Flush pending records and stop the background worker."""
        self._stop_event.set()
        try:
            self._queue.put_nowait(
                LokiLogEntry(labels={}, timestamp_ns="0", line="")
            )
        except queue.Full:
            pass
        if self._worker.is_alive():
            self._worker.join(timeout=self._flush_interval * 2)
        super().close()

    def _build_entry(self, record: logging.LogRecord) -> LokiLogEntry | None:
        try:
            line = self.format(record)
        except Exception:
            return None
        timestamp_ns = str(int(record.created * 1_000_000_000))
        labels = self._build_labels(record)
        if not labels:
            return None
        return LokiLogEntry(labels=labels, timestamp_ns=timestamp_ns, line=line)

    def _build_labels(self, record: logging.LogRecord) -> dict[str, str]:
        labels: dict[str, str] = {}
        if self._component:
            labels["component"] = str(self._component)
        if self._host:
            labels["host"] = str(self._host)
        if self._run_id:
            labels["run_id"] = str(self._run_id)
        if self._workload:
            labels["workload"] = str(self._workload)
        if self._package:
            labels["package"] = str(self._package)
        if self._plugin:
            labels["plugin"] = str(self._plugin)
        if self._scenario:
            labels["scenario"] = str(self._scenario)
        if self._repetition is not None:
            labels["repetition"] = str(self._repetition)

        record_labels = getattr(record, "lb_labels", None)
        if isinstance(record_labels, Mapping):
            for key, value in record_labels.items():
                if value is None:
                    continue
                labels[str(key)] = str(value)

        phase = getattr(record, "lb_phase", None)
        if phase is not None:
            labels["phase"] = str(phase)

        for key, value in self._labels.items():
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

    def _run_worker(self) -> None:
        pending: list[LokiLogEntry] = []
        next_flush = time.monotonic() + self._flush_interval
        while not self._stop_event.is_set() or not self._queue.empty() or pending:
            timeout = max(0.0, next_flush - time.monotonic())
            try:
                entry = self._queue.get(timeout=timeout)
                if entry.line or entry.labels:
                    pending.append(entry)
                self._queue.task_done()
            except queue.Empty:
                pass

            now = time.monotonic()
            if pending and (len(pending) >= self._batch_size or now >= next_flush):
                self._push_entries(pending)
                pending = []
                next_flush = now + self._flush_interval

        if pending:
            self._push_entries(pending)

    def _push_entries(self, entries: list[LokiLogEntry]) -> None:
        payload = build_loki_payload(entries)
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        req = request.Request(self._endpoint, data=data, headers=headers, method="POST")

        for attempt in range(self._max_retries + 1):
            try:
                with request.urlopen(req, timeout=self._timeout_seconds) as resp:
                    if 200 <= resp.status < 300:
                        return
            except error.HTTPError as exc:
                if 400 <= exc.code < 500:
                    _logger.debug(
                        "Loki push rejected (HTTP %d), dropping %d entries",
                        exc.code,
                        len(entries),
                    )
                    return
                _logger.debug(
                    "Loki push failed (HTTP %d), attempt %d/%d",
                    exc.code,
                    attempt + 1,
                    self._max_retries + 1,
                )
            except Exception as exc:
                _logger.debug(
                    "Loki push error: %s, attempt %d/%d",
                    exc,
                    attempt + 1,
                    self._max_retries + 1,
                )
            if attempt < self._max_retries and self._backoff_base > 0:
                delay = self._backoff_base * (self._backoff_factor ** attempt)
                time.sleep(delay)
        _logger.debug(
            "Loki push failed after %d attempts, dropping %d entries",
            self._max_retries + 1,
            len(entries),
        )
