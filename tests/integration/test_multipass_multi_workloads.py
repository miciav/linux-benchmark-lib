import os
from pathlib import Path

import pytest

from benchmark_config import (
    BenchmarkConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    StressNGConfig,
    DDConfig,
    FIOConfig,
)
from controller import AnsibleRunnerExecutor, BenchmarkController
from tests.integration.test_multipass_benchmark import multipass_vm


@pytest.mark.integration
def test_remote_multiple_workloads(multipass_vm, tmp_path):
    """
    Run a short multipass-based integration across multiple workloads.

    Workloads: stress-ng, dd, fio. Durations and sizes are trimmed to keep
    runtime reasonable in CI.
    """
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
        stress_ng=StressNGConfig(cpu_workers=1, timeout=3),
        dd=DDConfig(bs="1M", count=32, of_path="/tmp/dd_test"),
        fio=FIOConfig(
            runtime=5,
            size="64M",
            numjobs=1,
            iodepth=4,
            directory="/tmp",
            name="benchmark",
            rw="randrw",
            bs="4k",
            output_format="json",
        ),
    )

    ansible_dir = tmp_path / "ansible_data"
    os.environ["ANSIBLE_ROLES_PATH"] = str(Path("ansible/roles").absolute())
    os.environ["ANSIBLE_CONFIG"] = str(Path("ansible/ansible.cfg").absolute())
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    executor = AnsibleRunnerExecutor(private_data_dir=ansible_dir, stream_output=True)
    controller = BenchmarkController(config, executor=executor)

    summary = controller.run(["stress_ng", "dd", "fio"], run_id="multi_run")

    assert summary.success, f"Benchmark failed. Phases: {summary.phases}"
    for phase in ("setup", "run", "collect"):
        assert phase in summary.phases and summary.phases[phase].success

    for vm in multipass_vms:
        host_output_dir = summary.per_host_output[vm["name"]]
        assert host_output_dir.exists()
        files = list(host_output_dir.rglob("*"))
        assert files, f"No result files were collected for {vm['name']}."
