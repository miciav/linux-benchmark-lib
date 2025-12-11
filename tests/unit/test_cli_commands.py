"""CLI behavior tests using Typer's CliRunner."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import lb_ui.cli as cli

pytestmark = [pytest.mark.unit, pytest.mark.cli]

from lb_controller.contracts import BenchmarkConfig, RemoteHostConfig, WorkloadConfig
from lb_controller.services.config_service import ConfigService
from lb_controller.services.run_service import RunContext, RunResult


runner = CliRunner()


class DummyRegistry:
    def available(self):
        return {"dummy": object()}

    def get(self, name):
        return object()

    def create_generator(self, plugin_name, options=None):
        class G:
            def _validate_environment(self):
                return True
        return G()


class FakeRunService:
    def __init__(self):
        self.contexts = []
        self.executions = []
        self._container_runner = None

    def build_context(self, cfg, tests, remote_override=None, **kwargs):
        context = RunContext(
            config=cfg,
            target_tests=["dummy"],
            registry=DummyRegistry(),
            use_remote=False if remote_override is None else remote_override,
            use_container=kwargs.get("docker", False),
            config_path=kwargs.get("config_path"),
            docker_image=kwargs.get("docker_image", "linux-benchmark-lib:dev"),
            docker_engine=kwargs.get("docker_engine", "docker"),
            docker_build=kwargs.get("docker_build", True),
            docker_no_cache=kwargs.get("docker_no_cache", False),
        )
        self.contexts.append((cfg, tests, remote_override, kwargs))
        return context

    def create_session(self, config_service, tests=None, config_path=None, setup=True, **kwargs):
        # Mimic what RunService.create_session does partially
        cfg, _, _ = config_service.load_for_read(config_path)
        
        # Extract args that build_context expects as positional
        remote = kwargs.get("remote")
        
        # In the real implementation, tests defaults to all enabled workloads
        target_tests = tests or ["dummy"] # simplification for test
        
        # Call build_context to record the interaction
        return self.build_context(cfg, target_tests, remote_override=remote, **kwargs)

    def execute(self, context, run_id=None, **kwargs):
        self.executions.append((context, run_id, kwargs))
        return RunResult(context=context, summary=None)


def test_run_uses_run_service(monkeypatch):
    """CLI run command should delegate orchestration to RunService."""
    fake_service = FakeRunService()
    monkeypatch.setattr(cli, "run_service", fake_service)
    monkeypatch.setattr(cli, "_print_run_plan", lambda *args, **kwargs: None)

    # Avoid side effects by overriding config loader
    cfg = BenchmarkConfig()
    cfg.workloads = {"dummy": WorkloadConfig(plugin="stress_ng", enabled=True)}
    monkeypatch.setattr(cli.config_service, "load_for_read", lambda path: (cfg, None, None))

    result = runner.invoke(cli.app, ["run", "--no-remote"])

    assert result.exit_code == 0
    assert fake_service.contexts, "RunService.build_context was not called"
    assert fake_service.executions, "RunService.execute was not called"


def test_run_docker_flag(monkeypatch):
    """Docker flag should set use_container in the run context."""
    monkeypatch.setattr(cli, "DEV_MODE", True)
    fake_service = FakeRunService()
    fake_service._container_runner = type("CR", (), {"run": lambda self, spec: None})()  # noqa: SLF001
    monkeypatch.setattr(cli, "run_service", fake_service)
    monkeypatch.setattr(cli, "_print_run_plan", lambda *args, **kwargs: None)
    cfg = BenchmarkConfig()
    cfg.workloads = {"dummy": WorkloadConfig(plugin="stress_ng", enabled=True)}
    monkeypatch.setattr(cli.config_service, "load_for_read", lambda path: (cfg, None, None))

    result = runner.invoke(cli.app, ["run", "--docker"])

    assert result.exit_code == 0
    ctx_args = fake_service.contexts[0]
    assert ctx_args[0] == cfg
    assert ctx_args[2] is None  # remote override
    assert ctx_args[3].get("docker") is True
    assert fake_service.executions, "RunService.execute was not called"


def test_config_enable_workload_uses_service(tmp_path, monkeypatch):
    """Config enable/disable should persist through ConfigService."""
    config_service = ConfigService(config_home=tmp_path / "config")
    monkeypatch.setattr(cli, "config_service", config_service)

    target = tmp_path / "cfg.json"
    result = runner.invoke(
        cli.app,
        ["config", "enable-workload", "stress_ng", "--config", str(target)],
    )

    assert result.exit_code == 0
    loaded = BenchmarkConfig.load(target)
    assert loaded.workloads["stress_ng"].enabled is True


def test_plugins_command_lists_registry(monkeypatch):
    """Plugins command should succeed even with empty registry."""
    monkeypatch.setattr(cli, "create_registry", lambda: DummyRegistry())
    monkeypatch.setattr(cli, "build_plugin_table", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(cli.ui, "show_table", lambda *args, **kwargs: None)
    result = runner.invoke(cli.app, ["plugin", "ls"])
    # Dummy registry yields available workload placeholder
    assert result.exit_code == 0
