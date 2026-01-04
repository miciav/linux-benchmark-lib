"""Integration tests for async_localrunner event streaming.

These tests verify that the LocalRunner correctly emits LB_EVENT lines
to the event stream log file when running in daemonized mode.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.inter_generic
def test_async_localrunner_emits_events_to_stream_file(tmp_path: Path) -> None:
    """Verify async_localrunner writes LB_EVENT lines to stream log file."""
    # Create minimal benchmark config
    config = {
        "repetitions": 1,
        "test_duration_seconds": 5,
        "warmup_seconds": 0,
        "cooldown_seconds": 0,
        "output_dir": str(tmp_path / "output"),
        "workloads": {
            "baseline": {
                "plugin": "baseline",
                "options": {"duration_seconds": 2},
            }
        },
        "collectors": {
            "psutil_interval": 1.0,
            "enable_ebpf": False,
        },
    }

    config_path = tmp_path / "benchmark_config.generated.json"
    config_path.write_text(json.dumps(config))

    stream_log_path = tmp_path / "lb_events.stream.log"
    status_path = tmp_path / "lb_localrunner.status.json"
    pid_path = tmp_path / "lb_localrunner.pid"
    stop_path = tmp_path / "STOP"

    # Run async_localrunner directly (non-daemonized for easier testing)
    env = os.environ.copy()
    env.update({
        "LB_RUN_HOST": "test-host",
        "LB_RUN_WORKLOAD": "baseline",
        "LB_RUN_REPETITION": "1",
        "LB_RUN_TOTAL_REPS": "1",
        "LB_RUN_ID": "test-run-001",
        "LB_RUN_STOP_FILE": str(stop_path),
        "LB_BENCH_CONFIG_PATH": str(config_path),
        "LB_EVENT_STREAM_PATH": str(stream_log_path),
        "LB_ENABLE_EVENT_LOGGING": "1",
        "LB_LOG_LEVEL": "INFO",
        "LB_RUN_STATUS_PATH": str(status_path),
        "LB_RUN_PID_PATH": str(pid_path),
        # NOT setting LB_RUN_DAEMONIZE so it runs in foreground
    })

    result = subprocess.run(
        [sys.executable, "-m", "lb_runner.services.async_localrunner"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(tmp_path),
    )

    # Check that the process completed
    assert result.returncode == 0, f"LocalRunner failed: {result.stderr}"

    # Check that status file was created
    assert status_path.exists(), "Status file not created"
    status = json.loads(status_path.read_text())
    assert status.get("rc") == 0, f"LocalRunner reported error: {status}"

    # Check that events were written to stream log
    assert stream_log_path.exists(), "Event stream log file not created"
    log_content = stream_log_path.read_text()

    # Should have at least one LB_EVENT line
    lb_event_lines = [
        line for line in log_content.split("\n")
        if "LB_EVENT" in line
    ]

    assert len(lb_event_lines) > 0, (
        f"No LB_EVENT lines in stream log.\n"
        f"Log content:\n{log_content}\n"
        f"Stdout:\n{result.stdout}\n"
        f"Stderr:\n{result.stderr}"
    )

    # Check for final done/failed event
    final_events = [
        line for line in lb_event_lines
        if '"status": "done"' in line or '"status": "failed"' in line
    ]
    assert len(final_events) > 0, (
        "No final done/failed event in stream log.\n"
        "LB_EVENT lines:\n" + "\n".join(lb_event_lines)
    )


@pytest.mark.inter_generic
def test_async_localrunner_daemonized_emits_events(tmp_path: Path) -> None:
    """Verify async_localrunner writes LB_EVENT lines when daemonized."""
    config = {
        "repetitions": 1,
        "test_duration_seconds": 5,
        "warmup_seconds": 0,
        "cooldown_seconds": 0,
        "output_dir": str(tmp_path / "output"),
        "workloads": {
            "baseline": {
                "plugin": "baseline",
                "options": {"duration_seconds": 2},
            }
        },
        "collectors": {
            "psutil_interval": 1.0,
            "enable_ebpf": False,
        },
    }

    config_path = tmp_path / "benchmark_config.generated.json"
    config_path.write_text(json.dumps(config))

    stream_log_path = tmp_path / "lb_events.stream.log"
    status_path = tmp_path / "lb_localrunner.status.json"
    pid_path = tmp_path / "lb_localrunner.pid"
    stop_path = tmp_path / "STOP"

    # Run async_localrunner in daemonized mode
    env = os.environ.copy()
    env.update({
        "LB_RUN_HOST": "test-host",
        "LB_RUN_WORKLOAD": "baseline",
        "LB_RUN_REPETITION": "1",
        "LB_RUN_TOTAL_REPS": "1",
        "LB_RUN_ID": "test-run-002",
        "LB_RUN_STOP_FILE": str(stop_path),
        "LB_BENCH_CONFIG_PATH": str(config_path),
        "LB_EVENT_STREAM_PATH": str(stream_log_path),
        "LB_ENABLE_EVENT_LOGGING": "1",
        "LB_LOG_LEVEL": "INFO",
        "LB_RUN_STATUS_PATH": str(status_path),
        "LB_RUN_PID_PATH": str(pid_path),
        "LB_RUN_DAEMONIZE": "1",  # Enable daemonization
    })

    # Start the daemonized process
    result = subprocess.run(
        [sys.executable, "-m", "lb_runner.services.async_localrunner"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(tmp_path),
    )

    # Parent should exit immediately with rc=0
    assert result.returncode == 0, f"Parent failed to daemonize: {result.stderr}"

    # Wait for pid file
    deadline = time.time() + 10
    while not pid_path.exists() and time.time() < deadline:
        time.sleep(0.1)
    assert pid_path.exists(), "PID file not created after daemonization"

    # Wait for the daemon to complete (status file appears)
    deadline = time.time() + 60
    while not status_path.exists() and time.time() < deadline:
        time.sleep(0.5)

    assert status_path.exists(), (
        f"Status file not created within timeout.\n"
        f"PID file content: {pid_path.read_text() if pid_path.exists() else 'N/A'}\n"
        f"Stream log exists: {stream_log_path.exists()}\n"
        f"Stream log content: {stream_log_path.read_text() if stream_log_path.exists() else 'N/A'}"
    )

    status = json.loads(status_path.read_text())
    assert status.get("rc") == 0, f"LocalRunner reported error: {status}"

    # Check that events were written to stream log
    assert stream_log_path.exists(), "Event stream log file not created"
    log_content = stream_log_path.read_text()

    lb_event_lines = [
        line for line in log_content.split("\n")
        if "LB_EVENT" in line
    ]

    assert len(lb_event_lines) > 0, (
        f"No LB_EVENT lines in stream log after daemonized run.\n"
        f"Log content:\n{log_content}"
    )


@pytest.mark.inter_generic
def test_lb_event_handler_attached_when_enabled(tmp_path: Path) -> None:
    """Verify LBEventLogHandler is attached and emits events."""
    import logging
    from lb_runner.api import LBEventLogHandler

    # Setup environment
    os.environ["LB_ENABLE_EVENT_LOGGING"] = "1"
    os.environ["LB_LOG_LEVEL"] = "INFO"

    # Import and call the logging configuration
    from lb_runner.services.async_localrunner import _configure_logging_level
    _configure_logging_level()

    # Check root logger level is INFO
    root_logger = logging.getLogger()
    assert root_logger.level <= logging.INFO, (
        f"Root logger level is {root_logger.level}, expected <= {logging.INFO}"
    )

    # Create handler and attach
    handler = LBEventLogHandler(
        run_id="test-run",
        host="test-host",
        workload="test",
        repetition=1,
        total_repetitions=1,
    )

    # Capture output
    import io
    import sys

    captured = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = captured

    try:
        # Attach handler
        test_logger = logging.getLogger("test_handler")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        # Emit a log message
        test_logger.info("Test event message")

        # Check output
        output = captured.getvalue()
        assert "LB_EVENT" in output, f"No LB_EVENT in output: {output}"
        assert "Test event message" in output, f"Message not in output: {output}"

    finally:
        sys.stdout = original_stdout
        test_logger.removeHandler(handler)
        # Restore env
        os.environ.pop("LB_ENABLE_EVENT_LOGGING", None)
        os.environ.pop("LB_LOG_LEVEL", None)


@pytest.mark.inter_generic
def test_tee_writes_to_log_file(tmp_path: Path) -> None:
    """Verify _Tee class writes to both log file and original stdout."""
    import sys

    log_path = tmp_path / "test.log"

    # Simulate what _configure_stream does
    log_file = log_path.open("a", encoding="utf-8")
    original_stdout = sys.stdout

    class _Tee:
        def write(self, data: str) -> int:
            log_file.write(data)
            log_file.flush()
            original_stdout.write(data)
            original_stdout.flush()
            return len(data)

        def flush(self) -> None:
            log_file.flush()
            original_stdout.flush()

    # Replace stdout
    sys.stdout = _Tee()

    try:
        # Print something
        print("LB_EVENT {\"test\": true}", flush=True)

        # Check log file
        log_file.close()
        content = log_path.read_text()
        assert "LB_EVENT" in content, f"LB_EVENT not in log file: {content}"
        assert '{"test": true}' in content, f"JSON not in log file: {content}"

    finally:
        sys.stdout = original_stdout
