from pathlib import Path

from linux_benchmark_lib.benchmark_config import BenchmarkConfig, WorkloadConfig
from linux_benchmark_lib.plugin_system.builtin import builtin_plugins
from linux_benchmark_lib.plugin_system.registry import PluginRegistry
from linux_benchmark_lib.services.run_service import RunContext, RunService, RunResult, RunStatus


def test_container_run_updates_journal(tmp_path, monkeypatch):
    """Container mode should write journal/log with completed tasks even when docker is mocked."""
    cfg = BenchmarkConfig(output_dir=tmp_path / "benchmark_results")
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    registry = PluginRegistry(builtin_plugins())

    service = RunService(lambda: registry)
    # Avoid touching a real container engine
    monkeypatch.setattr(service._container_runner, "ensure_engine", lambda engine: None)

    def fake_run_workload(spec, workload_name, plugin):
        run_id = spec.run_id or "test-run"
        journal_dir = spec.artifacts_dir / run_id
        journal_dir.mkdir(parents=True, exist_ok=True)
        from linux_benchmark_lib.journal import RunJournal, RunStatus

        journal = RunJournal.initialize(run_id, cfg, [workload_name])
        host_name = cfg.remote_hosts[0].name if cfg.remote_hosts else "localhost"
        for rep in range(1, cfg.repetitions + 1):
            journal.update_task(host_name, workload_name, rep, RunStatus.COMPLETED, action="container_run")
        journal.save(journal_dir / "run_journal.json")
        (journal_dir / "run.log").write_text("ok")

    monkeypatch.setattr(service._container_runner, "run_workload", fake_run_workload)

    context = RunContext(
        config=cfg,
        target_tests=["stress_ng"],
        registry=registry,
        use_remote=False,
        use_container=True,
        use_multipass=False,
        multipass_count=1,
        config_path=None,
        docker_image="dummy",
        docker_engine="docker",
        docker_build=False,
        docker_no_cache=False,
        docker_workdir=tmp_path,  # mount-safe
        debug=False,
        resume_from=None,
        resume_latest=False,
    )

    result: RunResult = service.execute(context, run_id="test-run")
    assert result.journal_path and result.journal_path.exists()
    from linux_benchmark_lib.journal import RunJournal
    loaded = RunJournal.load(result.journal_path)
    tasks = list(loaded.tasks.values())
    assert tasks, "journal should contain tasks"
    assert all(t.status == RunStatus.COMPLETED for t in tasks)
    assert result.log_path and result.log_path.exists()
