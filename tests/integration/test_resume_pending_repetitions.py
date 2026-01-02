import pytest

from lb_controller.api import (
    BenchmarkController,
    BenchmarkConfig,
    ControllerOptions,
    ExecutionResult,
    RemoteHostConfig,
    RunJournal,
    RunStatus,
    WorkloadConfig,
)


pytestmark = pytest.mark.inter_generic


class FakeExecutor:
    def __init__(self) -> None:
        self.run_extravars = None
        self.run_playbook_path = None

    def run_playbook(
        self,
        playbook_path,
        inventory,
        extravars=None,
        tags=None,
        limit_hosts=None,
        *,
        cancellable=True,
    ):
        _ = (inventory, tags, limit_hosts, cancellable)
        if playbook_path.name == "run_benchmark.yml":
            self.run_playbook_path = playbook_path
            self.run_extravars = extravars or {}
        return ExecutionResult(rc=0, status="ok", stats={})


def test_resume_runs_pending_repetitions_only(tmp_path):
    cfg = BenchmarkConfig()
    cfg.output_dir = tmp_path / "benchmark_results"
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
    cfg.repetitions = 3
    cfg.remote_hosts = [RemoteHostConfig(name="node-1", address="10.0.0.1")]
    cfg.remote_execution.run_setup = False
    cfg.remote_execution.run_collect = False
    cfg.remote_execution.run_teardown = False

    run_id = "run-20250101-000001"
    journal = RunJournal.initialize(run_id, cfg, ["stress_ng"])
    journal.update_task("node-1", "stress_ng", 1, RunStatus.COMPLETED)
    journal_path = cfg.output_dir / run_id / "run_journal.json"
    journal.save(journal_path)

    executor = FakeExecutor()
    controller = BenchmarkController(cfg, ControllerOptions(executor=executor))

    controller.run(
        ["stress_ng"],
        run_id=run_id,
        journal=journal,
        resume=True,
        journal_path=journal_path,
    )

    assert executor.run_extravars is not None
    pending = executor.run_extravars.get("pending_repetitions", {})
    assert pending.get("node-1") == [2, 3]
