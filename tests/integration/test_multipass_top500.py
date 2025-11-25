import os
from pathlib import Path

import pytest

from benchmark_config import BenchmarkConfig, RemoteExecutionConfig, RemoteHostConfig, Top500Config
from controller import AnsibleRunnerExecutor, BenchmarkController
from tests.integration.test_multipass_benchmark import multipass_vm
from tests.integration.multipass_utils import get_intensity


@pytest.mark.integration
def test_remote_top500_setup_only(multipass_vm, tmp_path):
    """
    Run a lightweight Top500 playbook (setup tag only) on Multipass VM(s).

    This validates the Top500 workload path without running the full HPL benchmark.
    """
    _ = get_intensity()  # keep interface consistent; no runtime change for top500 setup
    multipass_vms = multipass_vm
    host_configs = [
        RemoteHostConfig(
            name=vm["name"],
            address=vm["ip"],
            user=vm["user"],
            become=True,
            vars={
                "ansible_ssh_private_key_file": str(vm["key_path"]),
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
            },
        )
        for vm in multipass_vms
    ]

    config = BenchmarkConfig(
        repetitions=1,
        test_duration_seconds=5,
        warmup_seconds=0,
        cooldown_seconds=0,
        output_dir=tmp_path / "results",
        report_dir=tmp_path / "reports",
        data_export_dir=tmp_path / "exports",
        remote_hosts=host_configs,
        remote_execution=RemoteExecutionConfig(
            enabled=True,
            run_setup=True,
            run_collect=True,
        ),
        top500=Top500Config(tags=["setup"]),
    )
    config.workloads["top500"].enabled = True

    ansible_dir = tmp_path / "ansible_data"
    os.environ["ANSIBLE_ROLES_PATH"] = str(Path("ansible/roles").absolute())
    os.environ["ANSIBLE_CONFIG"] = str(Path("ansible/ansible.cfg").absolute())
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    executor = AnsibleRunnerExecutor(private_data_dir=ansible_dir, stream_output=True)
    controller = BenchmarkController(config, executor=executor)

    summary = controller.run(["top500"], run_id="top500_setup")

    assert summary.success, f"Benchmark failed. Phases: {summary.phases}"
    for phase in ("setup", "run", "collect"):
        assert phase in summary.phases and summary.phases[phase].success

    for vm in multipass_vms:
        host_output_dir = summary.per_host_output[vm["name"]]
        assert host_output_dir.exists()
        files = list(host_output_dir.rglob("*"))
        assert files, f"No result files were collected for {vm['name']}."
