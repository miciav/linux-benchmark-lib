import json
import logging
import queue
from typing import Any

import pytest

from lb_common.logs.handlers.loki_handler import (
    LokiLogEntry,
    LokiPushHandler,
    build_loki_payload,
    normalize_loki_endpoint,
)


pytestmark = pytest.mark.unit_runner


def test_normalize_loki_endpoint_appends_push_path() -> None:
    endpoint = normalize_loki_endpoint("http://localhost:3100")
    assert endpoint.endswith("/loki/api/v1/push")


def test_normalize_loki_endpoint_preserves_complete_path() -> None:
    """Endpoint already ending with push path should not be duplicated."""
    endpoint = normalize_loki_endpoint("http://localhost:3100/loki/api/v1/push")
    assert endpoint == "http://localhost:3100/loki/api/v1/push"
    assert endpoint.count("/loki/api/v1/push") == 1


def test_normalize_loki_endpoint_strips_trailing_slash() -> None:
    endpoint = normalize_loki_endpoint("http://localhost:3100/")
    assert endpoint == "http://localhost:3100/loki/api/v1/push"


def test_loki_payload_groups_streams() -> None:
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


def test_loki_handler_builds_labels() -> None:
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


def test_loki_handler_label_overrides_from_record() -> None:
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
    record.lb_component = "generator"
    record.lb_host = "override-host"
    record.lb_run_id = "override-run"

    entry = handler._build_entry(record)
    assert entry is not None
    assert entry.labels["component"] == "generator"
    assert entry.labels["host"] == "override-host"
    assert entry.labels["run_id"] == "override-run"
    handler.close()


def test_loki_handler_emit_handles_queue_full(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When queue is full, emit should drop the entry and log DEBUG."""
    handler = LokiPushHandler(
        endpoint="http://localhost:3100",
        component="runner",
        host="host1",
        run_id="run-1",
        max_queue_size=1,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    def mock_put_nowait(entry: Any) -> None:
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

    with caplog.at_level(logging.DEBUG, logger="lb_common.logs.handlers.loki_handler"):
        handler.emit(record)

    assert any("queue full" in rec.message for rec in caplog.records)
    handler.close()


def test_loki_handler_emit_does_not_block() -> None:
    """emit() should use put_nowait and never block."""
    handler = LokiPushHandler(
        endpoint="http://localhost:3100",
        component="runner",
        host="host1",
        run_id="run-1",
        max_queue_size=2,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

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
        handler.emit(record)

    assert handler._queue.qsize() <= 2
    handler.close()


def test_loki_payload_empty_entries() -> None:
    """Empty entries list should produce empty streams."""
    payload = build_loki_payload([])
    assert payload == {"streams": []}


def test_loki_handler_retries_on_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handler should retry on network error."""
    handler = LokiPushHandler(
        endpoint="http://localhost:3100",
        component="runner",
        host="host1",
        run_id="run-1",
        max_retries=2,
        backoff_base=0.01,  # Fast retry for test
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Create a mock response context manager
    class MockResponse:
        def __init__(self, status: int) -> None:
            self.status = status
        def __enter__(self) -> "MockResponse":
            return self
        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    # Mock urlopen to fail once then succeed
    call_count = 0

    def mock_urlopen(req: Any, timeout: float) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            from urllib.error import HTTPError
            raise HTTPError(req.full_url, 503, "Service Unavailable", None, None)  # type: ignore[arg-type]
        return MockResponse(204)

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    # Force synchronous push for testing
    entry = LokiLogEntry(
        labels={"component": "runner"}, timestamp_ns="1", line="test"
    )
    handler._push_entries([entry])

    assert call_count == 2
    handler.close()
