from unittest.mock import MagicMock

import linux_benchmark_lib.services.container_service as container_service
from linux_benchmark_lib.services.container_service import ContainerRunSpec, ContainerRunner


def test_container_runner_forwards_repetitions(monkeypatch, tmp_path):
    runner = ContainerRunner()
    monkeypatch.setattr(runner, "ensure_engine", lambda engine: None)
    monkeypatch.setattr(runner, "build_plugin_image", lambda spec, plugin: "tag")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, check):
        captured["cmd"] = cmd

    monkeypatch.setattr(container_service.subprocess, "run", fake_run)

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
