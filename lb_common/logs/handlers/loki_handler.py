"""Loki push handler for non-blocking log shipping."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Iterable, Mapping, Any
from urllib import request, error
from urllib.parse import urlparse

from lb_common.logs.handlers.loki_helpers import LokiLabelBuilder, LokiWorker
from lb_common.logs.handlers.loki_types import LokiLogEntry

_logger = logging.getLogger(__name__)


def normalize_loki_endpoint(endpoint: str) -> str:
    """Return a Loki push URL (ending with /loki/api/v1/push)."""
    trimmed = endpoint.rstrip("/")
    _validate_http_url(trimmed, "Loki endpoint")
    if trimmed.endswith("/loki/api/v1/push"):
        return trimmed
    return f"{trimmed}/loki/api/v1/push"


def _validate_http_url(url: str, label: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be an http(s) URL, got: {url}")
    return url


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
        self._label_builder = LokiLabelBuilder(
            component=self._component,
            host=self._host,
            run_id=self._run_id,
            workload=self._workload,
            package=self._package,
            plugin=self._plugin,
            scenario=self._scenario,
            repetition=self._repetition,
            labels=self._labels,
        )
        self._worker = LokiWorker(
            queue=self._queue,
            stop_event=self._stop_event,
            batch_size=self._batch_size,
            flush_interval=self._flush_interval,
            push_entries=self._push_entries,
        )
        self._thread = threading.Thread(
            target=self._worker.run,
            name="loki-push-handler",
            daemon=True,
        )
        self._thread.start()

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
        if self._thread.is_alive():
            self._thread.join(timeout=self._flush_interval * 2)
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
        return self._label_builder.build(record)

    def _push_entries(self, entries: list[LokiLogEntry]) -> None:
        payload = build_loki_payload(entries)
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        req = request.Request(self._endpoint, data=data, headers=headers, method="POST")

        for attempt in range(self._max_retries + 1):
            if self._try_push(req, entries, attempt):
                return
            self._sleep_backoff(attempt)
        _logger.debug(
            "Loki push failed after %d attempts, dropping %d entries",
            self._max_retries + 1,
            len(entries),
        )

    def _try_push(
        self,
        req: request.Request,
        entries: list[LokiLogEntry],
        attempt: int,
    ) -> bool:
        try:
            with request.urlopen(  # nosec B310
                req, timeout=self._timeout_seconds
            ) as resp:
                if 200 <= resp.status < 300:
                    return True
        except error.HTTPError as exc:
            if 400 <= exc.code < 500:
                _logger.debug(
                    "Loki push rejected (HTTP %d), dropping %d entries",
                    exc.code,
                    len(entries),
                )
                return True
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
        return False

    def _sleep_backoff(self, attempt: int) -> None:
        if attempt < self._max_retries and self._backoff_base > 0:
            delay = self._backoff_base * (self._backoff_factor ** attempt)
            time.sleep(delay)
