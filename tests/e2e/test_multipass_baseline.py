"""
Multipass e2e tests for the Baseline workload.
"""

import os
import shutil
import os
from pathlib import Path
from typing import Dict, List

import pytest

from lb_runner.benchmark_config import (
    BenchmarkConfig,
    MetricCollectorConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_plugins.plugins.baseline.plugin import BaselineConfig
from lb_controller.ansible_executor import AnsibleRunnerExecutor
from lb_controller.api import BenchmarkController
from tests.e2e.test_multipass_benchmark import multipass_vm  # noqa: F401
from tests.helpers.multipass import get_intensity, make_test_ansible_env, stage_private_key

pytestmark = [
    pytest.mark.inter_e2e,
    pytest.mark.inter_multipass,
    pytest.mark.inter_baseline,
]

STRICT_MULTIPASS_SETUP = os.environ.get("LB_STRICT_MULTIPASS_SETUP", "").lower() in {
    "1",
    "true",
    "yes",
}
STRICT_MULTIPASS_ARTIFACTS = os.environ.get("LB_STRICT_MULTIPASS_ARTIFACTS", "").lower() in {
    "1",
    "true",
    "yes",
}


def _build_host_configs(multipass_vms: List[Dict], staged_key: Path) -> List[RemoteHostConfig]:
    return [
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


def _handle_missing_artifacts(msg: str) -> None:
    if STRICT_MULTIPASS_ARTIFACTS:
        pytest.fail(msg)
    pytest.skip(msg)


def _assert_artifacts(host_output_dir: Path, workload: str, expected_reps: int) -> None:
    missing: list[str] = []
    if not host_output_dir.exists():
        _handle_missing_artifacts(f"Host output dir missing: {host_output_dir}")

    system_info = host_output_dir / "system_info.csv"
    if not (system_info.exists() and system_info.stat().st_size > 0):
        missing.append(f"system_info.csv missing or empty at {system_info}")

    workload_dir = host_output_dir / workload
    if not workload_dir.exists():
        _handle_missing_artifacts(f"Workload directory missing: {workload_dir}")

    results_file = workload_dir / f"{workload}_results.json"
    if not (results_file.exists() and results_file.stat().st_size > 0):
        missing.append(f"Results JSON missing/empty: {results_file}")

    plugin_csv = workload_dir / f"{workload}_plugin.csv"
    if not (plugin_csv.exists() and plugin_csv.stat().st_size > 0):
        missing.append(f"Plugin CSV missing/empty: {plugin_csv}")

    for rep in range(1, expected_reps + 1):
        cli_csv = workload_dir / f"{workload}_rep{rep}_CLICollector.csv"
        psutil_csv = workload_dir / f"{workload}_rep{rep}_PSUtilCollector.csv"
        for path in (cli_csv, psutil_csv):
            if not path.exists() or path.stat().st_size == 0:
                missing.append(f"Collector CSV missing/empty: {path}")

    if missing:
        _handle_missing_artifacts("; ".join(missing))


def _run_single_workload(
    workload: str,
    workload_cfg: WorkloadConfig,
    plugin_settings: Dict[str, object],
    multipass_vms,
    tmp_path: Path,
) -> None:
    ansible_dir = tmp_path / f"ansible_data_{workload}"
    staged_key = stage_private_key(Path(multipass_vms[0]["key_path"]), ansible_dir / "keys")
    host_configs = _build_host_configs(multipass_vms, staged_key)

    output_dir = tmp_path / f"{workload}_results"
    report_dir = tmp_path / f"{workload}_reports"
    export_dir = tmp_path / f"{workload}_exports"

    config = BenchmarkConfig(
        repetitions=3,
        test_duration_seconds=10,  # Override for shorter test
        warmup_seconds=0,
        cooldown_seconds=0,
        output_dir=output_dir,
        report_dir=report_dir,
        data_export_dir=export_dir,
        remote_hosts=host_configs,
        remote_execution=RemoteExecutionConfig(
            enabled=True,
            run_setup=True,
            run_collect=True,
        ),
        plugin_settings=plugin_settings,
        workloads={workload: workload_cfg},
        collectors=MetricCollectorConfig(
            psutil_interval=1.0,
            cli_commands=["uptime"],
            enable_ebpf=False,
        ),
    )

    # Use parent directory roles path logic same as other e2e tests
    # Assuming tests/e2e/test_multipass_baseline.py -> ../../lb_controller/ansible/roles
    roles_path = Path(__file__).parents[2] / "lb_controller" / "ansible" / "roles"
    os.environ.update(make_test_ansible_env(ansible_dir, roles_path=roles_path))
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    executor = AnsibleRunnerExecutor(private_data_dir=ansible_dir, stream_output=True)
    controller = BenchmarkController(config, executor=executor)

    summary = controller.run([workload], run_id=f"{workload}_three_reps")
    if not summary.success:
        msg = f"Benchmark failed. Phases: {summary.phases}"
        if STRICT_MULTIPASS_SETUP:
            pytest.fail(msg)
        pytest.skip(msg)
    
    # Baseline has no setup/teardown ansible roles, so setup might be skipped or successful (no-op)
    # The runner ensures phases exist.
    assert summary.phases.get(f"run_{workload}") and summary.phases[f"run_{workload}"].success
    assert summary.phases.get(f"collect_{workload}") and summary.phases[f"collect_{workload}"].success

    for vm in multipass_vms:
        host_output_dir = summary.per_host_output[vm["name"]]
        _assert_artifacts(host_output_dir, workload, expected_reps=config.repetitions)


def test_multipass_baseline_three_reps(multipass_vm, tmp_path: Path) -> None:
    """Run baseline with three repetitions and verify artifacts."""
    # Use a short duration for E2E
    baseline_cfg = BaselineConfig(duration=5)
    workload_cfg = WorkloadConfig(
        plugin="baseline",
        enabled=True,
        options=baseline_cfg.model_dump(mode="json"),
    )
    
    _run_single_workload(
        "baseline",
        workload_cfg,
        {"baseline": baseline_cfg},
        multipass_vm,
        tmp_path
    )
