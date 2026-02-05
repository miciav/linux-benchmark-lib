import json
import logging
from datetime import datetime, timezone

import pytest

from lb_common.logs.schema import StructuredLogEvent


pytestmark = pytest.mark.unit_runner


def test_structured_log_event_serializes() -> None:
    event = StructuredLogEvent(
        timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
        level="INFO",
        component="runner",
        host="host1",
        run_id="run-1",
        logger="lb_runner.engine.runner",
        message="hello",
        event_type="log",
    )

    payload = json.loads(event.to_json())
    assert payload["timestamp"].startswith("2024-01-15T10:30:00")
    assert payload["component"] == "runner"
    assert payload["event_type"] == "log"


def test_structured_log_event_from_record() -> None:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    event = StructuredLogEvent.from_log_record(
        record,
        component="runner",
        host="host1",
        run_id="run-1",
        workload="stress_ng",
        repetition=1,
    )

    payload = json.loads(event.to_json())
    assert payload["message"] == "hello world"
    assert payload["workload"] == "stress_ng"
    assert payload["repetition"] == 1


def test_structured_log_event_with_package_plugin() -> None:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="test",
        args=(),
        exc_info=None,
    )
    event = StructuredLogEvent.from_log_record(
        record,
        component="test",
        host="host1",
        run_id="run-1",
        package="lb_plugins",
        plugin="dfaas",
    )

    payload = json.loads(event.to_json())
    assert payload["package"] == "lb_plugins"
    assert payload["plugin"] == "dfaas"
