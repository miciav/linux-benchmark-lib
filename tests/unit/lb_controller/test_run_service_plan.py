from dataclasses import dataclass

from lb_app.api import RunService
from lb_runner.api import BenchmarkConfig, WorkloadConfig


@dataclass
class DummyConfig:
    timeout: int = 5
    cpu_workers: int = 1


class DummyPlugin:
    name = "dummy"
    config_cls = DummyConfig

    def get_preset_config(self, level):  # noqa: D401
        return DummyConfig(timeout=5, cpu_workers=1)


class BrokenConfig:
    def __init__(self, *args, **kwargs):
        raise ValueError("boom")


class BrokenPlugin:
    name = "broken"
    config_cls = BrokenConfig

    def get_preset_config(self, level):
        return None


class DummyRegistry:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, name):
        return self._mapping[name]


def _make_config(workload: WorkloadConfig) -> BenchmarkConfig:
    cfg = BenchmarkConfig()
    cfg.workloads = {"task": workload}
    return cfg


def _service(registry) -> RunService:
    return RunService(lambda: registry)


def test_get_run_plan_remote_status_and_details():
    workload = WorkloadConfig(
        plugin="dummy",
        enabled=True,
        intensity="low",
        options={"timeout": 10, "cpu_workers": 2},
    )
    cfg = _make_config(workload)
    registry = DummyRegistry({"dummy": DummyPlugin()})

    plan = _service(registry).get_run_plan(
        cfg, ["task"], execution_mode="remote", registry=registry
    )

    assert len(plan) == 1
    item = plan[0]
    assert item["status"] == "[blue]Remote[/blue]"
    assert "Time: 5s" in item["details"]
    assert "CPU: 1" in item["details"]


def test_get_run_plan_missing_plugin_marks_missing():
    workload = WorkloadConfig(
        plugin="missing", enabled=True, intensity="user_defined", options={}
    )
    cfg = _make_config(workload)
    registry = DummyRegistry({})

    plan = _service(registry).get_run_plan(
        cfg, ["task"], execution_mode="remote", registry=registry
    )

    assert plan[0]["status"] == "[red]✗ (Missing)[/red]"
    assert plan[0]["details"] == "-"


def test_get_run_plan_config_error_surfaces_message():
    workload = WorkloadConfig(
        plugin="broken", enabled=True, intensity="user_defined", options={}
    )
    cfg = _make_config(workload)
    registry = DummyRegistry({"broken": BrokenPlugin()})

    plan = _service(registry).get_run_plan(
        cfg, ["task"], execution_mode="remote", registry=registry
    )

    assert "Config Error" in plan[0]["details"]
    assert plan[0]["status"] == "[blue]Remote[/blue]"


def test_get_run_plan_unknown_workload_uses_defaults():
    cfg = BenchmarkConfig()
    registry = DummyRegistry({})

    plan = _service(registry).get_run_plan(
        cfg, ["does_not_exist"], execution_mode="docker", registry=registry
    )

    assert plan[0]["plugin"] == "unknown"
    assert plan[0]["status"] == "[yellow]?[/yellow]"
    assert plan[0]["details"] == "-"
