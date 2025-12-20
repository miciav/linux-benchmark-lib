"""Unit tests for the log streaming mechanism."""

import json
import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from lb_runner.events import RunEvent
from lb_runner.log_handler import LBEventLogHandler
from lb_app.services.run_service import AnsibleOutputFormatter, _extract_lb_event_data


@pytest.mark.controller
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


@pytest.mark.controller
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


@pytest.mark.controller
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
    phase, message = result
    
    assert phase == "run h1 w1"
    assert message == "[WARNING] Something went wrong"


@pytest.mark.controller
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
    assert res_status == ("run h1 w1", "1/? running")
    
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
    assert res_log == ("run h1 w1", "[ERROR] Critical failure")
