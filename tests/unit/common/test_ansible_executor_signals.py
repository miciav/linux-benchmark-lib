"""Tests for AnsibleRunnerExecutor signal/session isolation."""

from types import SimpleNamespace

import pytest

from lb_controller.ansible_executor import AnsibleRunnerExecutor
from lb_controller.types import InventorySpec
from lb_runner.benchmark_config import RemoteHostConfig


@pytest.mark.controller
def test_subprocess_run_uses_new_session(monkeypatch, tmp_path):
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    execu = AnsibleRunnerExecutor(private_data_dir=tmp_path / "ansible", stream_output=False)
    playbook = tmp_path / "play.yml"
    playbook.write_text("- hosts: all\n  tasks: []\n")
    inventory = InventorySpec(
        hosts=[RemoteHostConfig(name="node1", address="127.0.0.1", user="root")]
    )

    execu.run_playbook(playbook, inventory)

    assert captured.get("start_new_session") is True


@pytest.mark.controller
def test_subprocess_popen_uses_new_session(monkeypatch, tmp_path):
    captured = {}

    class DummyStdout:
        def __init__(self) -> None:
            self._lines = iter(["", ""])

        def readline(self):
            try:
                return next(self._lines)
            except StopIteration:
                return ""

        def fileno(self):
            return 0

    class DummyProc:
        def __init__(self) -> None:
            self.stdout = DummyStdout()
            self._poll = 0
            self.returncode = None

        def poll(self):
            val = self._poll
            self._poll = 0
            return val

        def terminate(self):
            self._poll = 0

        def wait(self, timeout=None):
            self._poll = 0
            self.returncode = 0
            return self.returncode

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return DummyProc()

    class DummySelector:
        def register(self, *args, **kwargs):
            return None

        def select(self, timeout=None):
            return []

        def close(self):
            return None

    monkeypatch.setattr("selectors.DefaultSelector", lambda: DummySelector())
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    execu = AnsibleRunnerExecutor(private_data_dir=tmp_path / "ansible", stream_output=True, output_callback=lambda *_: None)
    playbook = tmp_path / "play.yml"
    playbook.write_text("- hosts: all\n  tasks: []\n")
    inventory = InventorySpec(
        hosts=[RemoteHostConfig(name="node1", address="127.0.0.1", user="root")]
    )

    execu.run_playbook(playbook, inventory)

    assert captured.get("start_new_session") is True
