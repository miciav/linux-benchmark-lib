"""Unit tests for RunProgressEmitter."""

from unittest.mock import MagicMock

import pytest

from lb_runner.engine.progress import RunProgressEmitter
from lb_runner.models.events import RunEvent


pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


class TestRunProgressEmitterInit:
    """Tests for RunProgressEmitter initialization."""

    def test_creates_with_host(self) -> None:
        """Emitter can be created with just a host."""
        emitter = RunProgressEmitter(host="node-1")
        assert emitter._host == "node-1"
        assert emitter._callback is None
        assert emitter._run_id == ""

    def test_creates_with_callback(self) -> None:
        """Emitter accepts an optional callback."""
        callback = MagicMock()
        emitter = RunProgressEmitter(host="node-1", callback=callback)
        assert emitter._callback is callback

    def test_creates_with_custom_stdout_emitter(self) -> None:
        """Emitter accepts a custom stdout emitter."""
        stdout_emitter = MagicMock()
        emitter = RunProgressEmitter(host="node-1", stdout_emitter=stdout_emitter)
        assert emitter._stdout_emitter is stdout_emitter


class TestRunProgressEmitterRunId:
    """Tests for run_id management."""

    def test_set_run_id(self) -> None:
        """set_run_id updates the run identifier."""
        emitter = RunProgressEmitter(host="node-1")
        emitter.set_run_id("run-123")
        assert emitter._run_id == "run-123"


class TestRunProgressEmitterEmit:
    """Tests for emit method."""

    def test_emit_calls_callback(self) -> None:
        """emit should call the callback with a RunEvent."""
        callback = MagicMock()
        emitter = RunProgressEmitter(host="node-1", callback=callback)
        emitter.set_run_id("run-1")

        emitter.emit("workload-a", 1, 3, "running")

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert isinstance(event, RunEvent)
        assert event.workload == "workload-a"
        assert event.repetition == 1
        assert event.total_repetitions == 3
        assert event.status == "running"
        assert event.run_id == "run-1"
        assert event.host == "node-1"

    def test_emit_includes_message(self) -> None:
        """emit should include optional message."""
        callback = MagicMock()
        emitter = RunProgressEmitter(host="node-1", callback=callback)

        emitter.emit("workload", 1, 1, "done", message="Success!")

        event = callback.call_args[0][0]
        assert event.message == "Success!"

    def test_emit_includes_error_info(self) -> None:
        """emit should include error_type and error_context."""
        callback = MagicMock()
        emitter = RunProgressEmitter(host="node-1", callback=callback)

        emitter.emit(
            "workload",
            1,
            1,
            "failed",
            error_type="WorkloadError",
            error_context={"cmd": "stress-ng"},
        )

        event = callback.call_args[0][0]
        assert event.error_type == "WorkloadError"
        assert event.error_context == {"cmd": "stress-ng"}

    def test_emit_calls_stdout_emitter(self) -> None:
        """emit should call stdout emitter."""
        stdout_emitter = MagicMock()
        emitter = RunProgressEmitter(host="node-1", stdout_emitter=stdout_emitter)

        emitter.emit("workload", 1, 1, "running")

        stdout_emitter.emit.assert_called_once()

    def test_emit_continues_on_callback_error(self) -> None:
        """emit should not raise if callback fails."""
        callback = MagicMock(side_effect=RuntimeError("callback error"))
        stdout_emitter = MagicMock()
        emitter = RunProgressEmitter(
            host="node-1", callback=callback, stdout_emitter=stdout_emitter
        )

        # Should not raise
        emitter.emit("workload", 1, 1, "running")

        # Stdout emitter should still be called
        stdout_emitter.emit.assert_called_once()

    def test_emit_continues_on_stdout_error(self) -> None:
        """emit should not raise if stdout emitter fails."""
        stdout_emitter = MagicMock()
        stdout_emitter.emit.side_effect = RuntimeError("stdout error")
        emitter = RunProgressEmitter(host="node-1", stdout_emitter=stdout_emitter)

        # Should not raise
        emitter.emit("workload", 1, 1, "running")
