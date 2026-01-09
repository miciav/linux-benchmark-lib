"""Tests for Loki logging helpers."""

from __future__ import annotations

import logging
import queue
import threading

import pytest

from lb_common.logs.handlers.loki_handler import LokiLogEntry
from lb_common.logs.handlers.loki_helpers import LokiLabelBuilder, LokiWorker


pytestmark = pytest.mark.unit_runner


def test_loki_label_builder_merges_overrides() -> None:
    builder = LokiLabelBuilder(
        component="runner",
        host="host1",
        run_id="run-1",
        workload=None,
        package=None,
        plugin=None,
        scenario=None,
        repetition=None,
        labels={"env": "prod"},
    )
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.lb_labels = {"custom": "1"}
    record.lb_host = "override-host"

    labels = builder.build(record)

    assert labels["host"] == "override-host"
    assert labels["env"] == "prod"
    assert labels["custom"] == "1"


def test_loki_worker_flushes_entries() -> None:
    q: queue.Queue[LokiLogEntry] = queue.Queue()
    stop_event = threading.Event()
    pushed: list[list[LokiLogEntry]] = []

    def push(entries: list[LokiLogEntry]) -> None:
        pushed.append(list(entries))

    worker = LokiWorker(
        queue=q,
        stop_event=stop_event,
        batch_size=1,
        flush_interval=0.1,
        push_entries=push,
    )
    q.put(LokiLogEntry(labels={"component": "runner"}, timestamp_ns="1", line="x"))
    stop_event.set()

    worker.run()

    assert pushed
    assert pushed[0][0].line == "x"
