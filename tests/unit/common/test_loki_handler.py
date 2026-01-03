import json
import logging
import queue

import pytest

from lb_common.handlers.loki_handler import (
    LokiLogEntry,
    LokiPushHandler,
    build_loki_payload,
    normalize_loki_endpoint,
)


pytestmark = pytest.mark.unit_runner


def test_normalize_loki_endpoint_appends_push_path():
    endpoint = normalize_loki_endpoint("http://localhost:3100")
    assert endpoint.endswith("/loki/api/v1/push")


def test_normalize_loki_endpoint_preserves_complete_path():
    """Endpoint already ending with push path should not be duplicated."""
    endpoint = normalize_loki_endpoint("http://localhost:3100/loki/api/v1/push")
    assert endpoint == "http://localhost:3100/loki/api/v1/push"
    assert endpoint.count("/loki/api/v1/push") == 1


def test_normalize_loki_endpoint_strips_trailing_slash():
    endpoint = normalize_loki_endpoint("http://localhost:3100/")
    assert endpoint == "http://localhost:3100/loki/api/v1/push"


def test_loki_payload_groups_streams():
    payload = build_loki_payload(
        [
            LokiLogEntry(
                labels={"component": "runner"}, timestamp_ns="1", line="a"
            ),
            LokiLogEntry(
                labels={"component": "runner"}, timestamp_ns="2", line="b"
            ),
            LokiLogEntry(labels={"component": "k6"}, timestamp_ns="3", line="c"),
        ]
    )
    streams = payload["streams"]
    assert len(streams) == 2
    runner_stream = next(
        stream for stream in streams if stream["stream"]["component"] == "runner"
    )
    assert runner_stream["values"] == [["1", "a"], ["2", "b"]]


def test_loki_handler_builds_labels():
    handler = LokiPushHandler(
        endpoint="http://localhost:3100",
        component="runner",
        host="host1",
        run_id="run-1",
        workload="stress_ng",
        repetition=1,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.lb_phase = "setup"
    record.lb_labels = {"env": "test"}

    entry = handler._build_entry(record)
    assert entry is not None
    labels = entry.labels
    assert labels["component"] == "runner"
    assert labels["host"] == "host1"
    assert labels["run_id"] == "run-1"
    assert labels["workload"] == "stress_ng"
    assert labels["repetition"] == "1"
    assert labels["phase"] == "setup"
    assert labels["env"] == "test"

    json.dumps(build_loki_payload([entry]))
    handler.close()


def test_loki_handler_label_overrides_from_record():
    """LogRecord attributes should override handler defaults."""
    handler = LokiPushHandler(
        endpoint="http://localhost:3100",
        component="runner",
        host="default-host",
        run_id="default-run",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    # These should override the handler defaults
    record.lb_component = "generator"
    record.lb_host = "override-host"
    record.lb_run_id = "override-run"

    entry = handler._build_entry(record)
    assert entry is not None
    assert entry.labels["component"] == "generator"
    assert entry.labels["host"] == "override-host"
    assert entry.labels["run_id"] == "override-run"
    handler.close()


def test_loki_handler_emit_handles_queue_full(caplog, monkeypatch):
    """When queue is full, emit should drop the entry and log DEBUG."""
    handler = LokiPushHandler(
        endpoint="http://localhost:3100",
        component="runner",
        host="host1",
        run_id="run-1",
        max_queue_size=1,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Mock put_nowait to raise queue.Full
    def mock_put_nowait(entry):
        raise queue.Full()

    monkeypatch.setattr(handler._queue, "put_nowait", mock_put_nowait)

    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="should be dropped",
        args=(),
        exc_info=None,
    )

    with caplog.at_level(logging.DEBUG, logger="lb_common.handlers.loki_handler"):
        handler.emit(record)  # Should not raise

    # Check that DEBUG was logged for queue full
    assert any("queue full" in rec.message for rec in caplog.records)
    handler.close()


def test_loki_handler_emit_does_not_block():
    """emit() should use put_nowait and never block."""
    handler = LokiPushHandler(
        endpoint="http://localhost:3100",
        component="runner",
        host="host1",
        run_id="run-1",
        max_queue_size=2,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Should not block even with rapid calls
    for i in range(5):
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=f"msg-{i}",
            args=(),
            exc_info=None,
        )
        handler.emit(record)  # Should not raise or block

    # At most max_queue_size items should be in queue
    assert handler._queue.qsize() <= 2
    handler.close()


def test_loki_payload_empty_entries():
    """Empty entries list should produce empty streams."""
    payload = build_loki_payload([])
    assert payload == {"streams": []}
