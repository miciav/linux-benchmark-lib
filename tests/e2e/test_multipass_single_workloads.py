"""
Multipass e2e tests that exercise each workload individually.

Each test runs three repetitions and validates that collector/plugin outputs
were produced and are non-empty inside the workload-specific directory.
"""

import os
from pathlib import Path
from typing import Dict, List

import pytest
import shutil
import platform

from lb_runner.benchmark_config import (
    BenchmarkConfig,
    MetricCollectorConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_runner.plugins.dd.plugin import DDConfig
from lb_runner.plugins.fio.plugin import FIOConfig
from lb_runner.plugins.geekbench.plugin import GeekbenchConfig
from lb_runner.plugins.hpl.plugin import HPLConfig
from lb_runner.plugins.stress_ng.plugin import StressNGConfig
from lb_runner.plugins.yabs.plugin import YabsConfig
from lb_controller.api import AnsibleRunnerExecutor, BenchmarkController
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
    duration_override_seconds: int | None = None,
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
        test_duration_seconds=duration_override_seconds or intensity["stress_duration"],
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
    workload_cfg = WorkloadConfig(
        plugin="stress_ng",
        enabled=True,
        options=stress_cfg.model_dump(mode="json"),
    )
    _run_single_workload("stress_ng", workload_cfg, {"stress_ng": stress_cfg}, multipass_vm, tmp_path)


def test_multipass_dd_three_reps(multipass_vm, tmp_path: Path) -> None:
    """Run dd with three repetitions and verify artifacts."""
    intensity = get_intensity()
    dd_cfg = DDConfig(bs="1M", count=intensity["dd_count"], of_path="/tmp/dd_test")
    workload_cfg = WorkloadConfig(
        plugin="dd",
        enabled=True,
        options=dd_cfg.model_dump(mode="json"),
    )
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
    workload_cfg = WorkloadConfig(
        plugin="fio",
        enabled=True,
        options=fio_cfg.model_dump(mode="json"),
    )
    _run_single_workload("fio", workload_cfg, {"fio": fio_cfg}, multipass_vm, tmp_path)


def test_multipass_geekbench_three_reps(multipass_vm, tmp_path: Path) -> None:
    """Run Geekbench with three repetitions and verify artifacts."""
    intensity = get_intensity()
    arch = platform.machine().lower()
    is_arm = "arm" in arch or "aarch64" in arch
    download_checksum = (
        # Geekbench 6.3.0 Linux ARM preview tarball.
        "7db7f4d6a6bdc31de4f63f0012abf7f1f00cdc5f6d64e727a47ff06bff6b6b04"
        if is_arm
        # Geekbench 6.3.0 Linux (x86_64) tarball.
        else "01727999719cd515a7224075dcab4876deef2844c45e8c2e9f34197224039f3b"
    )
    # Keep runtime bounded for e2e (Geekbench otherwise hints ~1800s).
    geek_cfg = GeekbenchConfig(
        output_dir=Path("/tmp"),
        skip_cleanup=True,
        run_gpu=False,
        expected_runtime_seconds=max(300, int(intensity.get("stress_timeout", 120))),
        download_checksum=download_checksum,
    )
    workload_cfg = WorkloadConfig(
        plugin="geekbench",
        enabled=True,
        options=geek_cfg.model_dump(mode="json"),
    )
    _run_single_workload(
        "geekbench",
        workload_cfg,
        {"geekbench": geek_cfg},
        multipass_vm,
        tmp_path,
        duration_override_seconds=geek_cfg.expected_runtime_seconds,
    )


def test_multipass_hpl_three_reps(multipass_vm, tmp_path: Path) -> None:
    """Run HPL with three repetitions and verify artifacts."""
    intensity = get_intensity()
    # Use a small problem size for e2e stability.
    hpl_cfg = HPLConfig(
        n=2000,
        nb=128,
        p=1,
        q=1,
        mpi_ranks=1,
        mpi_launcher="fork",
        expected_runtime_seconds=max(300, int(intensity.get("stress_timeout", 120))),
    )
    workload_cfg = WorkloadConfig(
        plugin="hpl",
        enabled=True,
        options=hpl_cfg.model_dump(mode="json"),
    )
    _run_single_workload(
        "hpl",
        workload_cfg,
        {"hpl": hpl_cfg},
        multipass_vm,
        tmp_path,
        duration_override_seconds=hpl_cfg.expected_runtime_seconds,
    )


def test_multipass_yabs_three_reps(multipass_vm, tmp_path: Path) -> None:
    """Run YABS with three repetitions and verify artifacts."""
    intensity = get_intensity()
    yabs_cfg = YabsConfig(
        script_url="https://raw.githubusercontent.com/masonr/yet-another-bench-script/8c0674518e1165fbf7c87ebe6f62d0e9a412dfef/yabs.sh",
        script_checksum="a3dbd700b76cd7439b7aa00c83bea7c85c738c53bd9ff1420e2c2b83bf8786b9",
        skip_disk=True,
        skip_network=True,
        skip_geekbench=True,
        skip_cleanup=True,
        expected_runtime_seconds=max(600, int(intensity.get("stress_timeout", 120))),
    )
    workload_cfg = WorkloadConfig(
        plugin="yabs",
        enabled=True,
        options=yabs_cfg.model_dump(mode="json"),
    )
    _run_single_workload(
        "yabs",
        workload_cfg,
        {"yabs": yabs_cfg},
        multipass_vm,
        tmp_path,
        duration_override_seconds=yabs_cfg.expected_runtime_seconds,
    )
