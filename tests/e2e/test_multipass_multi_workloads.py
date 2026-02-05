import os
from pathlib import Path

import pytest

from lb_controller.api import (
    AnsibleRunnerExecutor,
    BenchmarkController,
    ControllerOptions,
)
from lb_plugins.api import DDConfig, FIOConfig, StressNGConfig
from lb_runner.api import (
    BenchmarkConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from tests.helpers.multipass import (
    get_intensity,
    make_test_ansible_env,
    stage_private_key,
)

pytestmark = [pytest.mark.inter_e2e, pytest.mark.inter_multipass, pytest.mark.slowest]
pytest_plugins = ["tests.e2e.test_multipass_benchmark"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_ROOT = REPO_ROOT / "lb_controller" / "ansible"


@pytest.mark.inter_generic
def test_remote_multiple_workloads(multipass_vm, tmp_path):
    """
    Run a short multipass-based integration across multiple workloads.

    Workloads: stress-ng, dd, fio. Durations and sizes are trimmed to keep
    runtime reasonable in CI.
    """
    intensity = get_intensity()
    multipass_vms = multipass_vm
    ansible_dir = tmp_path / "ansible_data"
    staged_key = stage_private_key(
        Path(multipass_vms[0]["key_path"]),
        ansible_dir / "keys",
    )
    host_configs = [
        RemoteHostConfig(
            name=vm["name"],
            address=vm["ip"],
            user=vm["user"],
            become=True,
            vars={
                "ansible_ssh_private_key_file": str(staged_key),
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
            },
        )
        for vm in multipass_vms
    ]

    stress_cfg = StressNGConfig(cpu_workers=1, timeout=intensity["stress_timeout"])
    dd_cfg = DDConfig(bs="1M", count=intensity["dd_count"], of_path="/tmp/dd_test")
    fio_cfg = FIOConfig(
        runtime=intensity["fio_runtime"],
        size=intensity["fio_size"],
        numjobs=1,
        iodepth=4,
        directory="/tmp",
        name="benchmark",
        rw="randrw",
        bs="4k",
        output_format="json",
    )

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
        plugin_settings={
            "stress_ng": stress_cfg,
            "dd": dd_cfg,
            "fio": fio_cfg,
        },
        workloads={
            "stress_ng": WorkloadConfig(
                plugin="stress_ng",
                options=stress_cfg.model_dump(mode="json"),
            ),
            "dd": WorkloadConfig(
                plugin="dd",
                options=dd_cfg.model_dump(mode="json"),
            ),
            "fio": WorkloadConfig(
                plugin="fio",
                options=fio_cfg.model_dump(mode="json"),
            ),
        },
    )

    os.environ.update(
        make_test_ansible_env(ansible_dir, roles_path=ANSIBLE_ROOT / "roles")
    )
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    executor = AnsibleRunnerExecutor(private_data_dir=ansible_dir, stream_output=True)
    controller = BenchmarkController(config, ControllerOptions(executor=executor))

    summary = controller.run(["stress_ng", "dd", "fio"], run_id="multi_run")

    assert summary.success, f"Benchmark failed. Phases: {summary.phases}"
    for workload in ("stress_ng", "dd", "fio"):
        assert summary.phases.get(f"setup_{workload}", None) is not None
        assert summary.phases[f"setup_{workload}"].success
        assert summary.phases.get(f"run_{workload}", None) is not None
        assert summary.phases[f"run_{workload}"].success
        assert summary.phases.get(f"collect_{workload}", None) is not None
        assert summary.phases[f"collect_{workload}"].success

    for vm in multipass_vms:
        host_output_dir = summary.per_host_output[vm["name"]]
        assert host_output_dir.exists()
        files = list(host_output_dir.rglob("*"))
        assert files, f"No result files were collected for {vm['name']}."
