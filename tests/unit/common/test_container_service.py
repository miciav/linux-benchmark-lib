from unittest.mock import MagicMock

import pytest

import lb_controller.services.container_service as container_service
from lb_controller.services.container_service import ContainerRunSpec, ContainerRunner

pytestmark = pytest.mark.unit



def test_container_runner_forwards_repetitions(monkeypatch, tmp_path):
    runner = ContainerRunner()
    monkeypatch.setattr(runner, "ensure_engine", lambda engine: None)
    monkeypatch.setattr(runner, "build_plugin_image", lambda spec, plugin, **kwargs: "tag")

    captured: dict[str, list[str]] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        mock = MagicMock()
        mock.stdout = ["line1\n", "line2\n"]
        mock.wait.return_value = None
        mock.returncode = 0
        return mock

    monkeypatch.setattr(container_service.subprocess, "Popen", fake_popen)

    spec = ContainerRunSpec(
        tests=["stress_ng"],
        cfg_path=None,
        config_path=None,
        run_id=None,
        remote=False,
        image="img",
        workdir=tmp_path,
        artifacts_dir=tmp_path / "out",
        repetitions=4,
    )

    runner.run_workload(spec, "stress_ng", MagicMock(name="stress_ng"))

    assert "--repetitions" in captured["cmd"]
    assert "4" in captured["cmd"]


def test_container_runner_uses_lb_ui_cli(monkeypatch, tmp_path):
    runner = ContainerRunner()
    monkeypatch.setattr(runner, "ensure_engine", lambda engine: None)
    monkeypatch.setattr(runner, "build_plugin_image", lambda spec, plugin, **kwargs: "tag")

    captured: dict[str, list[str]] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        mock = MagicMock()
        mock.stdout = []
        mock.wait.return_value = None
        mock.returncode = 0
        return mock

    monkeypatch.setattr(container_service.subprocess, "Popen", fake_popen)

    spec = ContainerRunSpec(
        tests=["dd"],
        cfg_path=None,
        config_path=None,
        run_id=None,
        remote=False,
        image="img",
        workdir=tmp_path,
        artifacts_dir=tmp_path / "out",
        repetitions=1,
    )

    runner.run_workload(spec, "dd", MagicMock(name="dd"))

    assert "lb_ui.cli" in captured["cmd"], f"Expected lb_ui.cli in container command: {captured.get('cmd')}"
