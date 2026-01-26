"""Unit tests for RunWorker and UIHooksAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestUIHooksAdapter:
    """Tests for UIHooksAdapter signal emission."""

    def test_on_log_emits_signal(self) -> None:
        """Test that on_log emits log_line signal."""
        from lb_gui.workers.run_worker import UIHooksAdapter, RunWorkerSignals

        signals = RunWorkerSignals()
        signals.log_line = MagicMock()
        adapter = UIHooksAdapter(signals)

        adapter.on_log("test log line")

        signals.log_line.emit.assert_called_once_with("test log line")

    def test_on_status_emits_signal(self) -> None:
        """Test that on_status emits status_line signal."""
        from lb_gui.workers.run_worker import UIHooksAdapter, RunWorkerSignals

        signals = RunWorkerSignals()
        signals.status_line = MagicMock()
        adapter = UIHooksAdapter(signals)

        adapter.on_status("Running")

        signals.status_line.emit.assert_called_once_with("Running")

    def test_on_warning_emits_signal_with_ttl(self) -> None:
        """Test that on_warning emits warning signal with TTL."""
        from lb_gui.workers.run_worker import UIHooksAdapter, RunWorkerSignals

        signals = RunWorkerSignals()
        signals.warning = MagicMock()
        adapter = UIHooksAdapter(signals)

        adapter.on_warning("Warning message", ttl=5.0)

        signals.warning.emit.assert_called_once_with("Warning message", 5.0)

    def test_on_warning_uses_default_ttl(self) -> None:
        """Test that on_warning uses default TTL of 10.0."""
        from lb_gui.workers.run_worker import UIHooksAdapter, RunWorkerSignals

        signals = RunWorkerSignals()
        signals.warning = MagicMock()
        adapter = UIHooksAdapter(signals)

        adapter.on_warning("Warning message")

        signals.warning.emit.assert_called_once_with("Warning message", 10.0)

    def test_on_event_emits_signal(self) -> None:
        """Test that on_event emits event_update signal."""
        from lb_gui.workers.run_worker import UIHooksAdapter, RunWorkerSignals

        signals = RunWorkerSignals()
        signals.event_update = MagicMock()
        adapter = UIHooksAdapter(signals)
        mock_event = MagicMock()

        adapter.on_event(mock_event)

        signals.event_update.emit.assert_called_once_with(mock_event)

    def test_on_journal_emits_signal(self) -> None:
        """Test that on_journal emits journal_update signal."""
        from lb_gui.workers.run_worker import UIHooksAdapter, RunWorkerSignals

        signals = RunWorkerSignals()
        signals.journal_update = MagicMock()
        adapter = UIHooksAdapter(signals)
        mock_journal = MagicMock()

        adapter.on_journal(mock_journal)

        signals.journal_update.emit.assert_called_once_with(mock_journal)


class TestRunWorkerSignals:
    """Tests for RunWorkerSignals."""

    def test_signals_are_defined(self) -> None:
        """Test that all required signals are defined."""
        from lb_gui.workers.run_worker import RunWorkerSignals

        signals = RunWorkerSignals()

        # Verify all signals exist
        assert hasattr(signals, "log_line")
        assert hasattr(signals, "status_line")
        assert hasattr(signals, "warning")
        assert hasattr(signals, "event_update")
        assert hasattr(signals, "journal_update")
        assert hasattr(signals, "finished")
