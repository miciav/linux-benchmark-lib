import pytest

from lb_app.api import (
    ApplicationClient,
    BenchmarkConfig,
    RemoteHostConfig,
    RemoteHostSpec,
    RunJournal,
    WorkloadConfig,
)
from lb_provisioner.api import ProvisionedNode, ProvisioningError, ProvisioningResult


pytestmark = pytest.mark.unit_ui


class FakeProvisioner:
    def __init__(self) -> None:
        self.request = None

    def provision(self, request):
        self.request = request
        names = request.node_names or ["node-1"]
        nodes = [
            ProvisionedNode(
                host=RemoteHostSpec(
                    name=name,
                    address="127.0.0.1",
                )
            )
            for name in names
        ]
        return ProvisioningResult(nodes=nodes)


def _make_config(tmp_path, host_names=None) -> BenchmarkConfig:
    cfg = BenchmarkConfig()
    cfg.output_dir = tmp_path / "benchmark_results"
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
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


def _write_journal(cfg: BenchmarkConfig, run_id: str) -> None:
    journal = RunJournal.initialize(run_id, cfg, ["stress_ng"])
    journal_path = cfg.output_dir / run_id / "run_journal.json"
    journal.save(journal_path)


def test_provision_resume_uses_journal_node_names(tmp_path):
    cfg = _make_config(tmp_path, host_names=["node-b", "node-a"])
    run_id = "run-20250101-000000"
    _write_journal(cfg, run_id)

    client = ApplicationClient()
    fake = FakeProvisioner()
    client._provisioner = fake

    updated, _ = client._provision(
        cfg,
        "docker",
        node_count=2,
        resume=run_id,
    )

    assert fake.request.node_names == ["node-a", "node-b"]
    assert [host.name for host in updated.remote_hosts] == ["node-a", "node-b"]


def test_provision_resume_falls_back_to_run_dirs(tmp_path):
    cfg = _make_config(tmp_path)
    run_id = "run-20250101-000001"
    run_root = cfg.output_dir / run_id
    (run_root / "node-2").mkdir(parents=True)
    (run_root / "node-1").mkdir(parents=True)

    client = ApplicationClient()
    fake = FakeProvisioner()
    client._provisioner = fake

    client._provision(
        cfg,
        "multipass",
        node_count=2,
        resume=run_id,
    )

    assert fake.request.node_names == ["node-1", "node-2"]


def test_provision_resume_requires_node_names(tmp_path):
    cfg = _make_config(tmp_path)
    run_id = "run-20250101-000002"
    (cfg.output_dir / run_id).mkdir(parents=True)

    client = ApplicationClient()
    client._provisioner = FakeProvisioner()

    with pytest.raises(ProvisioningError, match="previous container/VM names"):
        client._provision(
            cfg,
            "docker",
            node_count=1,
            resume=run_id,
        )


def test_provision_resume_requires_matching_node_count(tmp_path):
    cfg = _make_config(tmp_path, host_names=["node-a", "node-b"])
    run_id = "run-20250101-000003"
    _write_journal(cfg, run_id)

    client = ApplicationClient()
    client._provisioner = FakeProvisioner()

    with pytest.raises(ProvisioningError, match="Resume node count does not match"):
        client._provision(
            cfg,
            "docker",
            node_count=1,
            resume=run_id,
        )
