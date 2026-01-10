import pytest

from lb_app.api import (
    BenchmarkConfig,
    PluginRegistry,
    RemoteHostConfig,
    RunContext,
    RunJournal,
    RunService,
    WorkloadConfig,
)


pytestmark = pytest.mark.unit_controller


def _make_config(tmp_path, host_names=None) -> BenchmarkConfig:
    cfg = BenchmarkConfig()
    cfg.output_dir = tmp_path / "benchmark_results"
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    cfg.repetitions = 1
    if host_names:
        cfg.remote_hosts = [
            RemoteHostConfig(
                name=name,
                address=f"10.0.0.{idx + 1}",
            )
            for idx, name in enumerate(host_names)
        ]
    return cfg


def _make_context(cfg: BenchmarkConfig, **overrides) -> RunContext:
    base = {
        "config": cfg,
        "target_tests": ["stress_ng"],
        "registry": PluginRegistry({}),
        "config_path": None,
        "debug": False,
        "resume_from": None,
        "resume_latest": False,
        "stop_file": None,
        "execution_mode": "remote",
        "node_count": None,
    }
    base.update(overrides)
    return RunContext(**base)


def test_new_journal_sets_execution_mode_and_node_count(tmp_path):
    cfg = _make_config(tmp_path)
    context = _make_context(cfg, execution_mode="docker")
    service = RunService(lambda: PluginRegistry({}))

    journal, _, _, _ = service._session_manager._prepare_journal_and_dashboard(
        context, run_id=None, ui_adapter=None
    )

    assert journal.metadata["execution_mode"] == "docker"
    assert journal.metadata["node_count"] == 1


def test_resume_journal_populates_metadata_when_missing(tmp_path):
    cfg = _make_config(tmp_path)
    run_id = "run-20250101-000000"
    journal = RunJournal.initialize(run_id, cfg, ["stress_ng"])
    journal_path = cfg.output_dir / run_id / "run_journal.json"
    journal.save(journal_path)

    context = _make_context(
        cfg,
        resume_from=run_id,
        execution_mode="multipass",
        node_count=2,
    )
    service = RunService(lambda: PluginRegistry({}))

    resumed, _, _, _ = service._session_manager._prepare_journal_and_dashboard(
        context, run_id=None, ui_adapter=None
    )

    assert resumed.metadata["execution_mode"] == "multipass"
    assert resumed.metadata["node_count"] == 2


def test_remote_node_count_defaults_to_host_count(tmp_path):
    cfg = _make_config(tmp_path, host_names=["node-a", "node-b"])
    context = _make_context(cfg, execution_mode="remote")
    service = RunService(lambda: PluginRegistry({}))

    journal, _, _, _ = service._session_manager._prepare_journal_and_dashboard(
        context, run_id=None, ui_adapter=None
    )

    assert journal.metadata["node_count"] == 2
