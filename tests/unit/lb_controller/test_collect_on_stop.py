from types import SimpleNamespace

import pytest

from lb_controller.adapters import playbooks

pytestmark = [pytest.mark.unit_controller]


def _make_state() -> SimpleNamespace:
    return SimpleNamespace(inventory="inv", extravars={})


def test_collect_runs_even_when_stop_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_execute(*_args, **_kwargs) -> None:
        calls.append("run")

    def fake_collect(*_args, **_kwargs) -> None:
        calls.append("collect")

    def fake_teardown(*_args, **_kwargs) -> None:
        calls.append("teardown")

    monkeypatch.setattr(playbooks, "execute_run_playbook", fake_execute)
    monkeypatch.setattr(playbooks, "handle_collect_phase", fake_collect)
    monkeypatch.setattr(playbooks, "run_teardown_playbook", fake_teardown)

    stop_token = SimpleNamespace(should_stop=lambda: True)
    controller = SimpleNamespace(
        stop_token=stop_token,
        _handle_stop_during_workloads=lambda *_a, **_k: None,
    )

    playbooks.run_workload_execution(
        controller,
        test_name="stress_ng",
        plugin_assets=None,
        plugin_name="stress_ng",
        state=_make_state(),
        pending_hosts=[],
        pending_reps={"host": [1]},
        phases={},
        flags=SimpleNamespace(),
        ui_log=lambda _msg: None,
    )

    assert calls == ["run", "collect"]


def test_collect_runs_when_run_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_execute(*_args, **_kwargs) -> None:
        calls.append("run")
        raise RuntimeError("boom")

    def fake_collect(*_args, **_kwargs) -> None:
        calls.append("collect")

    monkeypatch.setattr(playbooks, "execute_run_playbook", fake_execute)
    monkeypatch.setattr(playbooks, "handle_collect_phase", fake_collect)
    monkeypatch.setattr(playbooks, "run_teardown_playbook", lambda *_a, **_k: None)

    stop_token = SimpleNamespace(should_stop=lambda: False)
    controller = SimpleNamespace(stop_token=stop_token)

    with pytest.raises(RuntimeError):
        playbooks.run_workload_execution(
            controller,
            test_name="stress_ng",
            plugin_assets=None,
            plugin_name="stress_ng",
            state=_make_state(),
            pending_hosts=[],
            pending_reps={"host": [1]},
            phases={},
            flags=SimpleNamespace(),
            ui_log=lambda _msg: None,
        )

    assert calls == ["run", "collect"]
