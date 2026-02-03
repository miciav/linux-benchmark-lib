import pytest

from types import SimpleNamespace

from lb_app.api import (
    ApplicationClient,
    BenchmarkConfig,
    RemoteHostConfig,
    RunJournal,
    RunRequest,
    WorkloadConfig,
)
from lb_common.api import RemoteHostSpec
from lb_provisioner.api import ProvisionedNode


pytestmark = pytest.mark.inter_generic


class FakeProvisioner:
    def __init__(self) -> None:
        self.request = None

    def provision(self, request):
        self.request = request
        names = request.node_names or []
        return [
            ProvisionedNode(
                host=RemoteHostSpec(name=name, address="127.0.0.1")
            )
            for name in names
        ]


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


@pytest.mark.parametrize("mode", ["docker", "multipass"])
def test_resume_provisioning_preserves_node_names(tmp_path, mode):
    cfg = BenchmarkConfig()
    cfg.output_dir = tmp_path / "benchmark_results"
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    cfg.repetitions = 2
    cfg.remote_hosts = [
        RemoteHostConfig(name="lb-node-b", address="10.0.0.2"),
        RemoteHostConfig(name="lb-node-a", address="10.0.0.1"),
    ]

    run_id = "run-20250101-000000"
    journal = RunJournal.initialize(run_id, cfg, ["stress_ng"])
    journal_path = cfg.output_dir / run_id / "run_journal.json"
    journal.save(journal_path)

    client = ApplicationClient()
    fake_provisioner = FakeProvisioner()
    if mode == "docker":
        client._provisioner._docker = fake_provisioner
    else:
        client._provisioner._multipass = fake_provisioner

    def fake_execute(*_args, **_kwargs):
        return SimpleNamespace(
            summary=None,
            journal_path=None,
            log_path=None,
            ui_log_path=None,
        )

    client._run_service.execute = fake_execute

    request = RunRequest(
        config=cfg,
        tests=["stress_ng"],
        resume=run_id,
        execution_mode=mode,
        node_count=2,
        docker_engine="docker",
    )

    client.start_run(request, _Hooks())

    assert fake_provisioner.request is not None
    assert fake_provisioner.request.node_names == ["lb-node-a", "lb-node-b"]
    assert [host.name for host in cfg.remote_hosts] == ["lb-node-a", "lb-node-b"]
