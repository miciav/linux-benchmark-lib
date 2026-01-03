from types import SimpleNamespace

import pytest

from lb_controller import controller_playbooks


pytestmark = [pytest.mark.unit_controller]


def _make_state():
    return SimpleNamespace(inventory="inv", extravars={})


def test_collect_runs_even_when_stop_requested(monkeypatch):
    calls = []

    def fake_execute(*_args, **_kwargs):
        calls.append("run")

    def fake_collect(*_args, **_kwargs):
        calls.append("collect")

    def fake_teardown(*_args, **_kwargs):
        calls.append("teardown")

    monkeypatch.setattr(controller_playbooks, "execute_run_playbook", fake_execute)
    monkeypatch.setattr(controller_playbooks, "handle_collect_phase", fake_collect)
    monkeypatch.setattr(controller_playbooks, "run_teardown_playbook", fake_teardown)

    stop_token = SimpleNamespace(should_stop=lambda: True)
    controller = SimpleNamespace(stop_token=stop_token)

    controller_playbooks.run_workload_execution(
        controller,
        test_name="stress_ng",
        plugin=object(),
        state=_make_state(),
        pending_hosts=[],
        pending_reps={"host": [1]},
        phases={},
        flags=SimpleNamespace(),
        ui_log=lambda _msg: None,
    )

    assert calls == ["run", "collect"]


def test_collect_runs_when_run_raises(monkeypatch):
    calls = []

    def fake_execute(*_args, **_kwargs):
        calls.append("run")
        raise RuntimeError("boom")

    def fake_collect(*_args, **_kwargs):
        calls.append("collect")

    monkeypatch.setattr(controller_playbooks, "execute_run_playbook", fake_execute)
    monkeypatch.setattr(controller_playbooks, "handle_collect_phase", fake_collect)
    monkeypatch.setattr(controller_playbooks, "run_teardown_playbook", lambda *_a, **_k: None)

    stop_token = SimpleNamespace(should_stop=lambda: False)
    controller = SimpleNamespace(stop_token=stop_token)

    with pytest.raises(RuntimeError):
        controller_playbooks.run_workload_execution(
            controller,
            test_name="stress_ng",
            plugin=object(),
            state=_make_state(),
            pending_hosts=[],
            pending_reps={"host": [1]},
            phases={},
            flags=SimpleNamespace(),
            ui_log=lambda _msg: None,
        )

    assert calls == ["run", "collect"]
