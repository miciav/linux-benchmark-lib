import pytest

from lb_controller.services.run_service import RunService, RunContext, RunResult
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig, RemoteHostConfig
from lb_runner.plugin_system.registry import PluginRegistry
import lb_controller.controller as controller_module
import lb_controller.services.run_service as run_service_module


pytestmark = pytest.mark.controller


class DummyController:
    def __init__(self):
        self.called = False

    def run(self, *args, **kwargs):
        self.called = True
        class _Summary:
            success = True
            phases = {}
        return _Summary()


def test_run_service_uses_controller_runner(monkeypatch):
    cfg = BenchmarkConfig()
    cfg.workloads = {"dummy": WorkloadConfig(plugin="stress_ng", enabled=True)}
    cfg.remote_hosts = [
        RemoteHostConfig(
            name="host1",
            address="127.0.0.1",
            user="root",
            become=False,
            vars={"ansible_connection": "local"},
        )
    ]
    registry = PluginRegistry({})

    context = RunContext(
        config=cfg,
        target_tests=["dummy"],
        registry=registry,
        config_path=None,
        debug=False,
        resume_from=None,
        resume_latest=False,
        stop_file=None,
        execution_mode="remote",
    )

    dummy_controller = DummyController()
    monkeypatch.setattr(controller_module, "BenchmarkController", lambda *a, **k: dummy_controller)

    run_called = {"flag": False}

    class FakeRunner:
        def __init__(self, run_callable, **_kwargs):
            self._run_callable = run_callable

        def start(self):
            return None

        def wait(self, timeout=None):
            run_called["flag"] = True
            return self._run_callable()

    monkeypatch.setattr(run_service_module, "ControllerRunner", FakeRunner)

    service = RunService(lambda: registry)

    result: RunResult = service._run_remote(
        context=context,
        run_id="test",
        output_callback=lambda _t, end="": None,
        formatter=None,
        ui_adapter=None,
    )

    assert run_called["flag"] is True
    assert isinstance(result, RunResult)
