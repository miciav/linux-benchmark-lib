"""Unit tests for the log streaming mechanism."""

import json
import logging

import pytest

from lb_runner.api import RunEvent
from lb_runner.api import LBEventLogHandler
from lb_runner.services.async_localrunner import _configure_logging_level
from lb_app.api import AnsibleOutputFormatter, _extract_lb_event_data


@pytest.mark.unit_controller
def test_run_event_defaults():
    """Verify RunEvent has correct default values for new fields."""
    event = RunEvent(
        run_id="test-run",
        host="localhost",
        workload="test",
        repetition=1,
        total_repetitions=1,
        status="running",
    )
    assert event.type == "status"
    assert event.level == "INFO"
    
    as_dict = event.to_dict()
    assert as_dict["type"] == "status"
    assert as_dict["level"] == "INFO"


@pytest.mark.unit_controller
def test_lb_event_log_handler_emit(capsys):
    """Verify LBEventLogHandler emits correctly formatted JSON to stdout."""
    handler = LBEventLogHandler(
        run_id="run-123",
        host="node1",
        workload="stress_ng",
        repetition=2,
        total_repetitions=5
    )
    
    logger = logging.getLogger("test_logger")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    
    logger.info("Test message")
    
    captured = capsys.readouterr()
    stdout = captured.out.strip()
    
    assert stdout.startswith("LB_EVENT")
    payload_str = stdout.replace("LB_EVENT ", "")
    payload = json.loads(payload_str)
    
    assert payload["run_id"] == "run-123"
    assert payload["host"] == "node1"
    assert payload["workload"] == "stress_ng"
    assert payload["repetition"] == 2
    assert payload["total_repetitions"] == 5
    assert payload["status"] == "running"
    assert payload["type"] == "log"
    assert payload["level"] == "INFO"
    assert payload["message"] == "Test message"
    assert payload["logger"] == "test_logger"
    assert "timestamp" in payload


@pytest.mark.unit_controller
def test_ansible_output_formatter_log_parsing():
    """Verify AnsibleOutputFormatter correctly parses log events."""
    formatter = AnsibleOutputFormatter()
    
    # Construct a raw line as it would appear from Ansible stdout
    payload = {
        "run_id": "r1",
        "host": "h1",
        "workload": "w1",
        "repetition": 1,
        "total_repetitions": 1,
        "status": "running",
        "type": "log",
        "level": "WARNING",
        "message": "Something went wrong"
    }
    line = f"LB_EVENT {json.dumps(payload)}"
    
    # Verify parsing helper first
    extracted = _extract_lb_event_data(line)
    assert extracted is not None
    assert extracted["type"] == "log"
    
    # Verify formatter logic
    result = formatter._format_progress(line)
    assert result is not None
    phase, message, host = result
    
    assert phase == "run w1"
    assert message == "[WARNING] Something went wrong"
    assert host == "h1"


@pytest.mark.unit_controller
def test_ansible_output_formatter_mixed_input():
    """Verify parser handles mixed Ansible output correctly."""
    formatter = AnsibleOutputFormatter()
    
    # Normal status event
    status_payload = {
        "host": "h1",
        "workload": "w1",
        "repetition": 1,
        "status": "running",
        "type": "status"
    }
    status_line = f"LB_EVENT {json.dumps(status_payload)}"
    
    res_status = formatter._format_progress(status_line)
    assert res_status == ("run w1", "1/? running", "h1")
    
    # Log event inside an Ansible task output line (simulated)
    log_payload = {
        "host": "h1",
        "workload": "w1",
        "repetition": 1,
        "status": "running",
        "type": "log",
        "level": "ERROR",
        "message": "Critical failure"
    }
    # Ansible often wraps output in quotes or escapes
    log_line = f'msg: LB_EVENT {json.dumps(log_payload)}'

    res_log = formatter._format_progress(log_line)
    assert res_log == ("run w1", "[ERROR] Critical failure", "h1")


@pytest.mark.unit_controller
def test_configure_logging_level_sets_info_when_event_logging_enabled(monkeypatch):
    """Verify _configure_logging_level sets INFO when LB_ENABLE_EVENT_LOGGING=1."""
    monkeypatch.setenv("LB_ENABLE_EVENT_LOGGING", "1")
    monkeypatch.delenv("LB_LOG_LEVEL", raising=False)

    root_logger = logging.getLogger()
    original_level = root_logger.level

    try:
        # Reset to WARNING to simulate default state
        root_logger.setLevel(logging.WARNING)

        _configure_logging_level()

        assert root_logger.level == logging.INFO
    finally:
        root_logger.setLevel(original_level)


@pytest.mark.unit_controller
def test_configure_logging_level_respects_lb_log_level_env(monkeypatch):
    """Verify _configure_logging_level uses LB_LOG_LEVEL env var."""
    monkeypatch.setenv("LB_ENABLE_EVENT_LOGGING", "1")
    monkeypatch.setenv("LB_LOG_LEVEL", "DEBUG")

    root_logger = logging.getLogger()
    original_level = root_logger.level

    try:
        root_logger.setLevel(logging.WARNING)

        _configure_logging_level()

        assert root_logger.level == logging.DEBUG
    finally:
        root_logger.setLevel(original_level)


@pytest.mark.unit_controller
def test_configure_logging_level_noop_when_event_logging_disabled(monkeypatch):
    """Verify _configure_logging_level does nothing when event logging is off."""
    monkeypatch.setenv("LB_ENABLE_EVENT_LOGGING", "0")

    root_logger = logging.getLogger()
    original_level = root_logger.level

    try:
        root_logger.setLevel(logging.WARNING)

        _configure_logging_level()

        # Should remain at WARNING
        assert root_logger.level == logging.WARNING
    finally:
        root_logger.setLevel(original_level)


@pytest.mark.unit_controller
def test_configure_logging_level_does_not_raise_level(monkeypatch):
    """Verify _configure_logging_level doesn't raise level if already lower."""
    monkeypatch.setenv("LB_ENABLE_EVENT_LOGGING", "1")
    monkeypatch.delenv("LB_LOG_LEVEL", raising=False)

    root_logger = logging.getLogger()
    original_level = root_logger.level

    try:
        # Set to DEBUG (lower/more verbose than INFO)
        root_logger.setLevel(logging.DEBUG)

        _configure_logging_level()

        # Should remain at DEBUG
        assert root_logger.level == logging.DEBUG
    finally:
        root_logger.setLevel(original_level)
