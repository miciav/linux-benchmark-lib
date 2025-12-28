import shutil
import subprocess
import time
from pathlib import Path

import pytest

from lb_app.api import (
    ApplicationClient,
    BenchmarkConfig,
    RemoteHostConfig,
    RunJournal,
    RunRequest,
    RunStatus,
    WorkloadConfig,
)
from lb_controller.api import ExecutionResult


pytestmark = [pytest.mark.inter_docker, pytest.mark.slow]


class _Hooks:
    def on_log(self, line: str) -> None:
        pass

    def on_status(self, controller_state: str) -> None:
        pass

    def on_warning(self, message: str, ttl: float = 10.0) -> None:
        pass

    def on_event(self, event) -> None:
        pass

    def on_journal(self, journal) -> None:
        pass


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return False
    return True


def _docker_names() -> set[str]:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def test_resume_provisioning_real_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    if not _docker_ready():
        pytest.skip("Docker is not available or not running.")

    cfg = BenchmarkConfig()
    cfg.output_dir = tmp_path / "benchmark_results"
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
    cfg.repetitions = 3

    suffix = str(int(time.time()))
    expected_names = sorted(
        [f"lb-resume-a-{suffix}", f"lb-resume-b-{suffix}"]
    )
    cfg.remote_hosts = [
        RemoteHostConfig(name=name, address=f"10.0.0.{idx + 1}")
        for idx, name in enumerate(expected_names)
    ]

    run_id = f"run-20250101-0000{suffix}"
    journal = RunJournal.initialize(run_id, cfg, ["stress_ng"])
    for host in expected_names:
        journal.update_task(host, "stress_ng", 1, RunStatus.COMPLETED)
    journal.metadata["execution_mode"] = "docker"
    journal.metadata["node_count"] = 2
    journal_path = cfg.output_dir / run_id / "run_journal.json"
    journal.save(journal_path)

    class FakeExecutor:
        def __init__(self) -> None:
            self.playbook_paths = []
            self.run_extravars = None
            self._names_checked = False

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
            _ = (tags, limit_hosts, cancellable)
            self.playbook_paths.append(playbook_path)
            if not self._names_checked:
                names = _docker_names()
                missing = [name for name in expected_names if name not in names]
                if missing:
                    pytest.fail(
                        f"Provisioned containers missing in docker ps: {missing}"
                    )
                host_names = [host.name for host in inventory.hosts]
                assert sorted(host_names) == expected_names
                self._names_checked = True
            if playbook_path.name == "run_benchmark.yml":
                self.run_extravars = extravars or {}
            return ExecutionResult(rc=0, status="ok", stats={})

    fake_executor = FakeExecutor()
    client = ApplicationClient()
    from lb_app.services import run_service as run_service_module
    from lb_controller.api import BenchmarkController

    def fake_controller(*args, **kwargs):
        return BenchmarkController(*args, executor=fake_executor, **kwargs)

    monkeypatch.setattr(run_service_module, "BenchmarkController", fake_controller)

    request = RunRequest(
        config=cfg,
        tests=["stress_ng"],
        resume=run_id,
        execution_mode="docker",
        node_count=2,
        docker_engine="docker",
    )

    result = client.start_run(request, _Hooks())
    assert result is not None
    assert result.summary is not None
    assert result.summary.success is True

    pending = fake_executor.run_extravars.get("pending_repetitions", {})
    assert pending.get(expected_names[0]) == [2, 3]

    setup_playbook = cfg.remote_execution.setup_playbook
    run_playbook = cfg.remote_execution.run_playbook
    teardown_playbook = cfg.remote_execution.teardown_playbook
    assert setup_playbook in fake_executor.playbook_paths
    assert run_playbook in fake_executor.playbook_paths
    assert teardown_playbook in fake_executor.playbook_paths
