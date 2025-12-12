"""
Multipass e2e tests that exercise each workload individually.

Each test runs three repetitions and validates that collector/plugin outputs
were produced and are non-empty inside the workload-specific directory.
"""

import os
from dataclasses import asdict
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
from lb_runner.plugins.dd.plugin import DDConfig
from lb_runner.plugins.fio.plugin import FIOConfig
from lb_runner.plugins.stress_ng.plugin import StressNGConfig
from lb_controller.controller import AnsibleRunnerExecutor, BenchmarkController
from tests.e2e.test_multipass_benchmark import multipass_vm  # noqa: F401 - fixture import
from tests.helpers.multipass import get_intensity, make_test_ansible_env, stage_private_key

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.multipass,
    pytest.mark.slowest,
    pytest.mark.integration,
    pytest.mark.multipass_single,
]


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


def _assert_artifacts(host_output_dir: Path, workload: str, expected_reps: int) -> None:
    assert host_output_dir.exists()

    system_info = host_output_dir / "system_info.csv"
    assert system_info.exists() and system_info.stat().st_size > 0

    workload_dir = host_output_dir / workload
    assert workload_dir.exists(), f"Workload directory missing: {workload_dir}"

    results_file = workload_dir / f"{workload}_results.json"
    assert results_file.exists() and results_file.stat().st_size > 0

    plugin_csv = workload_dir / f"{workload}_plugin.csv"
    assert plugin_csv.exists() and plugin_csv.stat().st_size > 0

    for rep in range(1, expected_reps + 1):
        cli_csv = workload_dir / f"{workload}_rep{rep}_CLICollector.csv"
        psutil_csv = workload_dir / f"{workload}_rep{rep}_PSUtilCollector.csv"
        for path in (cli_csv, psutil_csv):
            assert path.exists(), f"Missing collector CSV: {path}"
            assert path.stat().st_size > 0, f"Collector CSV is empty: {path}"


def _run_single_workload(
    workload: str,
    workload_cfg: WorkloadConfig,
    plugin_settings: Dict[str, object],
    multipass_vms,
    tmp_path: Path,
) -> None:
    intensity = get_intensity()
    ansible_dir = tmp_path / f"ansible_data_{workload}"
    staged_key = stage_private_key(Path(multipass_vms[0]["key_path"]), ansible_dir / "keys")
    host_configs = _build_host_configs(multipass_vms, staged_key)

    output_dir = tmp_path / f"{workload}_results"
    report_dir = tmp_path / f"{workload}_reports"
    export_dir = tmp_path / f"{workload}_exports"

    config = BenchmarkConfig(
        repetitions=3,
        test_duration_seconds=intensity["stress_duration"],
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

    os.environ.update(make_test_ansible_env(ansible_dir, roles_path=Path(__file__).parents[2] / "lb_controller" / "ansible" / "roles"))
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    executor = AnsibleRunnerExecutor(private_data_dir=ansible_dir, stream_output=True)
    controller = BenchmarkController(config, executor=executor)

    summary = controller.run([workload], run_id=f"{workload}_three_reps")
    assert summary.success, f"Benchmark failed. Phases: {summary.phases}"
    assert summary.phases.get(f"setup_{workload}") and summary.phases[f"setup_{workload}"].success
    assert summary.phases.get(f"run_{workload}") and summary.phases[f"run_{workload}"].success
    assert summary.phases.get(f"collect_{workload}") and summary.phases[f"collect_{workload}"].success

    for vm in multipass_vms:
        host_output_dir = summary.per_host_output[vm["name"]]
        _assert_artifacts(host_output_dir, workload, expected_reps=config.repetitions)


def test_multipass_stress_ng_three_reps(multipass_vm, tmp_path: Path) -> None:
    """Run stress-ng with three repetitions and verify artifacts."""
    intensity = get_intensity()
    stress_cfg = StressNGConfig(cpu_workers=1, timeout=intensity["stress_timeout"])
    workload_cfg = WorkloadConfig(plugin="stress_ng", enabled=True, options=asdict(stress_cfg))
    _run_single_workload("stress_ng", workload_cfg, {"stress_ng": stress_cfg}, multipass_vm, tmp_path)


def test_multipass_dd_three_reps(multipass_vm, tmp_path: Path) -> None:
    """Run dd with three repetitions and verify artifacts."""
    intensity = get_intensity()
    dd_cfg = DDConfig(bs="1M", count=intensity["dd_count"], of_path="/tmp/dd_test")
    workload_cfg = WorkloadConfig(plugin="dd", enabled=True, options=asdict(dd_cfg))
    _run_single_workload("dd", workload_cfg, {"dd": dd_cfg}, multipass_vm, tmp_path)


def test_multipass_fio_three_reps(multipass_vm, tmp_path: Path) -> None:
    """Run fio with three repetitions and verify artifacts."""
    intensity = get_intensity()
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
    workload_cfg = WorkloadConfig(plugin="fio", enabled=True, options=asdict(fio_cfg))
    _run_single_workload("fio", workload_cfg, {"fio": fio_cfg}, multipass_vm, tmp_path)
