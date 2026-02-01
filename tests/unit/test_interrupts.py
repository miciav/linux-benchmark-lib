"""Unit tests for interrupt handling state machine."""

import signal
from unittest.mock import Mock, patch, ANY

import pytest

from lb_controller.api import DoubleCtrlCStateMachine, SigintDoublePressHandler
from lb_controller.api import RunInterruptState, SigintDecision


class TestDoubleCtrlCStateMachine:
    def test_initial_state(self):
        sm = DoubleCtrlCStateMachine()
        assert sm.state == RunInterruptState.RUNNING

    def test_inactive_run_delegates(self):
        sm = DoubleCtrlCStateMachine()
        decision = sm.on_sigint(run_active=False)
        assert decision == SigintDecision.DELEGATE
        assert sm.state == RunInterruptState.RUNNING

    def test_first_sigint_arms_stop(self):
        sm = DoubleCtrlCStateMachine()
        decision = sm.on_sigint(run_active=True)
        assert decision == SigintDecision.WARN_ARM
        assert sm.state == RunInterruptState.STOP_ARMED

    def test_second_sigint_requests_stop(self):
        sm = DoubleCtrlCStateMachine()
        # First press
        sm.on_sigint(run_active=True)
        # Second press
        decision = sm.on_sigint(run_active=True)
        assert decision == SigintDecision.REQUEST_STOP
        assert sm.state == RunInterruptState.STOPPING

    def test_third_sigint_delegates_force_kill(self):
        sm = DoubleCtrlCStateMachine()
        sm.on_sigint(run_active=True)  # Arm
        sm.on_sigint(run_active=True)  # Stop
        # Third press while stopping should be ignored while run is active
        decision = sm.on_sigint(run_active=True)
        assert decision == SigintDecision.IGNORE
        assert sm.state == RunInterruptState.STOPPING

    def test_finished_run_ignores_signals(self):
        sm = DoubleCtrlCStateMachine()
        sm.mark_finished()
        assert sm.state == RunInterruptState.FINISHED
        decision = sm.on_sigint(run_active=True)
        assert decision == SigintDecision.DELEGATE


class TestSigintDoublePressHandler:
    @pytest.fixture
    def mock_signal(self):
        with patch("signal.signal") as mock:
            yield mock

    @pytest.fixture
    def mock_getsignal(self):
        with patch("signal.getsignal") as mock:
            mock.return_value = signal.SIG_DFL
            yield mock

    def test_handler_install_and_restore(self, mock_signal, mock_getsignal):
        sm = Mock()
        sm.on_sigint.return_value = SigintDecision.WARN_ARM
        
        with SigintDoublePressHandler(
            state_machine=sm,
            run_active=lambda: True,
            on_first_sigint=Mock(),
            on_confirmed_sigint=Mock(),
        ):
            # Should install our handler
            mock_signal.assert_called_with(signal.SIGINT, ANY)
            handler_installed = mock_signal.call_args[0][1]
            
            # Simulate a signal call
            handler_installed(signal.SIGINT, None)
            sm.on_sigint.assert_called_once()

        # Should restore original handler (SIG_DFL)
        assert mock_signal.call_count == 2
        mock_signal.assert_called_with(signal.SIGINT, signal.SIG_DFL)
        mock_getsignal.assert_called_with(signal.SIGINT)

    def test_handler_routing(self, mock_signal, mock_getsignal):
        _ = mock_getsignal  # fixture ensures signals are patched
        sm = DoubleCtrlCStateMachine()
        on_first = Mock()
        on_confirmed = Mock()
        
        handler = SigintDoublePressHandler(
            state_machine=sm,
            run_active=lambda: True,
            on_first_sigint=on_first,
            on_confirmed_sigint=on_confirmed,
        )
        
        # We manually invoke _handle_sigint to test logic without dealing with real signal stack
        # 1. First press -> WARN_ARM
        handler._handle_sigint(signal.SIGINT, None)
        on_first.assert_called_once()
        on_confirmed.assert_not_called()
        
        # 2. Second press -> REQUEST_STOP
        handler._handle_sigint(signal.SIGINT, None)
        on_first.assert_called_once() # count stays 1
        on_confirmed.assert_called_once()

    def test_handler_skips_install_when_not_main_thread(self):
        sm = Mock()
        sm.on_sigint.return_value = SigintDecision.WARN_ARM
        dummy_thread = object()
        main_thread = object()

        with (
            patch("lb_controller.engine.interrupts.threading.current_thread", return_value=dummy_thread),
            patch("lb_controller.engine.interrupts.threading.main_thread", return_value=main_thread),
            patch("signal.signal", side_effect=ValueError("signal only works in main thread")) as mock_signal,
            patch("signal.getsignal") as mock_getsignal,
        ):
            with SigintDoublePressHandler(
                state_machine=sm,
                run_active=lambda: True,
                on_first_sigint=Mock(),
                on_confirmed_sigint=Mock(),
            ):
                pass

        mock_signal.assert_not_called()
        mock_getsignal.assert_not_called()
