import threading
import time

import pytest

from lb_controller.api import ControllerRunner
from lb_controller.api import ControllerState
from lb_runner.api import StopToken


pytestmark = pytest.mark.unit_controller


def test_runner_completes_and_emits_states():
    states: list[ControllerState] = []

    def on_state(state: ControllerState, _reason: str | None) -> None:
        states.append(state)

    runner = ControllerRunner(run_callable=lambda: "ok", stop_token=StopToken(enable_signals=False), on_state_change=on_state)
    runner.start()
    result = runner.wait(timeout=2.0)

    assert result == "ok"
    assert states[-1] == ControllerState.FINISHED


def test_runner_propagates_exceptions_as_failed():
    runner = ControllerRunner(run_callable=lambda: (_ for _ in ()).throw(RuntimeError("fail")), stop_token=StopToken(enable_signals=False))
    runner.start()
    with pytest.raises(RuntimeError):
        runner.wait(timeout=2.0)
    assert runner.exception is not None
    assert runner.state in (ControllerState.FAILED, ControllerState.ABORTED)


def test_runner_aborts_when_stop_requested():
    stop_token = StopToken(enable_signals=False)

    def _run():
        stop_token.request_stop()
        raise RuntimeError("stopped")

    runner = ControllerRunner(run_callable=_run, stop_token=stop_token, on_state_change=lambda *_: None)
    runner.start()
    with pytest.raises(RuntimeError):
        runner.wait(timeout=2.0)
    assert runner.state == ControllerState.ABORTED


def test_runner_stops_long_running_callable():
    stop_token = StopToken(enable_signals=False)
    ran = threading.Event()

    def _run():
        ran.set()
        while not stop_token.should_stop():
            time.sleep(0.05)
        return "stopped"

    runner = ControllerRunner(run_callable=_run, stop_token=stop_token)
    runner.start()
    assert ran.wait(timeout=1.0)
    stop_token.request_stop()
    result = runner.wait(timeout=2.0)
    assert result == "stopped"
    assert runner.state == ControllerState.ABORTED
