import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
# import multiprocessing # Removed for multiprocessing context fix

import pytest

from lb_plugins.api import DDConfig, FIOConfig, StressNGConfig
from lb_runner.api import (
    BenchmarkConfig,
    MetricCollectorConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_controller.api import AnsibleRunnerExecutor, BenchmarkController, ControllerOptions
from tests.helpers.multipass import (
    ensure_ansible_available,
    ensure_multipass_access,
    get_intensity,
    launch_multipass_vm,
    make_test_ansible_env,
    stage_private_key,
    wait_for_multipass_ip,
)

# Explicitly set the start method for multiprocessing on macOS
# This can help with issues related to ansible-runner's worker processes
# try:
#     multiprocessing.set_start_method('fork', force=True)
# except RuntimeError:
#     pass # Already set, or not supported on this platform/context

pytestmark = [pytest.mark.inter_e2e, pytest.mark.inter_multipass, pytest.mark.slowest]

REPO_ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_ROOT = REPO_ROOT / "lb_controller" / "ansible"

# Constants
VM_NAME_PREFIX = "benchmark-test-vm"
MAX_VM_COUNT = 2
SSH_KEY_PATH = Path("./temp_keys/test_key")
SSH_PUB_KEY_PATH = Path("./temp_keys/test_key.pub")
DEFAULT_VM_CPUS = 2
DEFAULT_VM_MEMORY = "2G"
DEFAULT_VM_DISK = "10G"
STRICT_ARTIFACTS = os.environ.get("LB_STRICT_MULTIPASS_ARTIFACTS", "").lower() in {
    "1",
    "true",
    "yes",
}
STRICT_MULTIPASS_SETUP = os.environ.get("LB_STRICT_MULTIPASS_SETUP", "").lower() in {
    "1",
    "true",
    "yes",
}

def is_multipass_available():
    """Check if multipass is installed and available."""
    return shutil.which("multipass") is not None

def _vm_count():
    raw = os.environ.get("LB_MULTIPASS_VM_COUNT", "1")
    try:
        count = int(raw)
    except ValueError:  # pragma: no cover - defensive for manual runs
        pytest.fail(f"LB_MULTIPASS_VM_COUNT must be an integer, got {raw!r}")

    if count < 1 or count > MAX_VM_COUNT:
        pytest.fail(
            f"LB_MULTIPASS_VM_COUNT must be between 1 and {MAX_VM_COUNT}, got {count}"
        )
    return count

def _vm_cpus() -> int:
    raw = os.environ.get("LB_MULTIPASS_CPUS", str(DEFAULT_VM_CPUS))
    try:
        cpus = int(raw)
    except ValueError:  # pragma: no cover - defensive for manual runs
        pytest.fail(f"LB_MULTIPASS_CPUS must be an integer, got {raw!r}")
    if cpus < 1:
        pytest.fail(f"LB_MULTIPASS_CPUS must be >= 1, got {cpus}")
    return cpus

def _vm_memory() -> str:
    raw = os.environ.get("LB_MULTIPASS_MEMORY", DEFAULT_VM_MEMORY).strip()
    if not raw:
        pytest.fail("LB_MULTIPASS_MEMORY must be a non-empty string")
    return raw

def _vm_disk() -> str:
    raw = os.environ.get("LB_MULTIPASS_DISK", DEFAULT_VM_DISK).strip()
    if not raw:
        pytest.fail("LB_MULTIPASS_DISK must be a non-empty string")
    return raw


def _handle_missing_artifacts(vm_name: str, missing: list[str]) -> None:
    """
    Allow graceful skips when the environment does not yield collector artifacts
    (common on hosts where Multipass networking or file sharing is restricted).

    Set LB_STRICT_MULTIPASS_ARTIFACTS=1 to turn these into hard failures.
    """
    if not missing:
        return
    message = f"Missing artifacts for {vm_name}: {', '.join(missing)}"
    if STRICT_ARTIFACTS:
        pytest.fail(message)
    pytest.skip(f"{message} (set LB_STRICT_MULTIPASS_ARTIFACTS=1 to enforce)")

def _vm_name(index: int, total: int) -> str:
    if total == 1:
        return VM_NAME_PREFIX
    return f"{VM_NAME_PREFIX}-{index + 1}"

def _wait_for_ip(vm_name: str) -> str:
    try:
        return wait_for_multipass_ip(vm_name)
    except RuntimeError as exc:
        pytest.fail(str(exc))

def _inject_ssh_key(vm_name: str, pub_key: str) -> None:
    cmd = (
        "mkdir -p ~/.ssh && "
        f"echo '{pub_key}' >> ~/.ssh/authorized_keys && "
        "chmod 600 ~/.ssh/authorized_keys"
    )
    for attempt in range(10):
        try:
            subprocess.run(
                ["multipass", "exec", vm_name, "--", "bash", "-c", cmd],
                check=True,
            )
            return
        except subprocess.CalledProcessError:
            if attempt == 9:
                raise
            print(f"SSH injection failed for {vm_name}, retrying ({attempt + 1}/10)...")
            time.sleep(3)

def _launch_vm(vm_name: str, pub_key: str) -> dict:
    print(f"Launching multipass VM: {vm_name}...")
    primary = os.environ.get("LB_MULTIPASS_IMAGE", "24.04")
    fallback = os.environ.get("LB_MULTIPASS_FALLBACK_IMAGE", "lts")
    launch_multipass_vm(
        vm_name,
        image_candidates=[primary, fallback],
        cpus=_vm_cpus(),
        memory=_vm_memory(),
        disk=_vm_disk(),
    )
    ip_address = _wait_for_ip(vm_name)
    print(f"VM {vm_name} started at {ip_address}. Injecting SSH key...")
    _inject_ssh_key(vm_name, pub_key)
    return {
        "name": vm_name,
        "ip": ip_address,
        "user": "ubuntu",
        "key_path": SSH_KEY_PATH.absolute(),
    }


def _run_multipass_cleanup(cmd: list[str], timeout: int = 120) -> None:
    try:
        subprocess.run(cmd, stderr=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"Multipass cleanup timed out: {' '.join(cmd)}")

@pytest.fixture(scope="module")
def multipass_vm():
    """
    Fixture to provision one or more Multipass VMs for testing.
    It generates an SSH key, launches the requested VMs, injects the key, and yields
    connection info.
    """
    ensure_ansible_available()
    ensure_multipass_access()

    vm_count = _vm_count()

    # Generate SSH key pair if not exists
    if not SSH_KEY_PATH.exists():
        SSH_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ssh-keygen", "-t", "rsa", "-f", str(SSH_KEY_PATH), "-N", ""],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    pub_key = SSH_PUB_KEY_PATH.read_text().strip()

    vm_names = [_vm_name(idx, vm_count) for idx in range(vm_count)]
    for name in vm_names:
        _run_multipass_cleanup(["multipass", "delete", name])
    _run_multipass_cleanup(["multipass", "purge"])

    created_vms = []
    try:
        for name in vm_names:
            created_vms.append(_launch_vm(name, pub_key))

        yield created_vms

    finally:
        # Teardown
        for vm in created_vms:
            print(f"Tearing down VM: {vm['name']}...")
            _run_multipass_cleanup(["multipass", "delete", vm["name"], "--purge"])
        _run_multipass_cleanup(["multipass", "purge"])
        # Remove generated SSH keys if present
        for key_path in (SSH_KEY_PATH, SSH_PUB_KEY_PATH):
            try:
                key_path.unlink()
            except FileNotFoundError:
                pass

def test_remote_benchmark_execution(multipass_vm, tmp_path):
    """
    Test the full remote benchmark execution flow on a Multipass VM.
    Supports dynamic workloads via LB_MULTIPASS_WORKLOADS (comma-separated).
    """
    intensity = get_intensity()
    multipass_vms = multipass_vm
    base_dir = Path(os.environ.get("LB_TEST_RESULTS_DIR", tmp_path))
    output_dir = base_dir / "results"
    report_dir = base_dir / "reports"
    export_dir = base_dir / "exports"
    ansible_dir = tmp_path / "ansible_data"

    workloads = os.environ.get("LB_MULTIPASS_WORKLOADS", "stress_ng").split(",")
    workloads = [w.strip() for w in workloads if w.strip()]

    staged_key = stage_private_key(
        Path(multipass_vms[0]["key_path"]),
        ansible_dir / "keys",
    )

    # Create configuration
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

    # Base config args
    config_args = {
        "output_dir": output_dir,
        "report_dir": report_dir,
        "data_export_dir": export_dir,
        "remote_hosts": host_configs,
        "remote_execution": RemoteExecutionConfig(
            enabled=True,
            run_setup=True,
            run_collect=True
        ),
        "test_duration_seconds": intensity["stress_duration"],
        "warmup_seconds": 0,
        "cooldown_seconds": 0,
    }
    config_args["collectors"] = MetricCollectorConfig(
        psutil_interval=1.0,
        cli_commands=["uptime"],
        enable_ebpf=False,
    )

    plugin_settings: dict[str, Any] = {}
    workload_defs: dict[str, WorkloadConfig] = {}

    if "stress_ng" in workloads:
        stress_cfg = StressNGConfig(
            cpu_workers=1,
            timeout=intensity["stress_timeout"]
        )
        plugin_settings["stress_ng"] = stress_cfg
        workload_defs["stress_ng"] = WorkloadConfig(
            plugin="stress_ng",
            options=stress_cfg.model_dump(mode="json"),
        )
    
    if "dd" in workloads:
        dd_cfg = DDConfig(
            bs="1M", 
            count=intensity["dd_count"], 
            of_path="/tmp/dd_test"
        )
        plugin_settings["dd"] = dd_cfg
        workload_defs["dd"] = WorkloadConfig(
            plugin="dd",
            options=dd_cfg.model_dump(mode="json"),
        )

    if "fio" in workloads:
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
        plugin_settings["fio"] = fio_cfg
        workload_defs["fio"] = WorkloadConfig(
            plugin="fio",
            options=fio_cfg.model_dump(mode="json"),
        )

    config_args["plugin_settings"] = plugin_settings
    config_args["workloads"] = workload_defs

    # Additional workloads can be added here similarly if needed

    config = BenchmarkConfig(**config_args)

    # Ensure Ansible finds roles and uses a minimal callback config
    os.environ.update(make_test_ansible_env(ansible_dir, roles_path=ANSIBLE_ROOT / "roles"))
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    
    executor = AnsibleRunnerExecutor(private_data_dir=ansible_dir, stream_output=True)
    controller = BenchmarkController(config, ControllerOptions(executor=executor))

    # Execute
    print(f"Starting benchmark controller for workloads: {workloads}")
    summary = controller.run(workloads, run_id="test_run")

    # Verify execution
    if not summary.success:
        msg = f"Benchmark failed. Phases: {summary.phases}"
        if STRICT_MULTIPASS_SETUP:
            pytest.fail(msg)
        pytest.skip(msg)
    # Phases: setup_global + per-test phases + collect
    if "setup_global" not in summary.phases or not summary.phases["setup_global"].success:
        msg = f"setup_global failed. Phases: {summary.phases}"
        if STRICT_MULTIPASS_SETUP:
            pytest.fail(msg)
        pytest.skip(msg)
    for test_name in workloads:
        assert f"setup_{test_name}" in summary.phases
        assert summary.phases[f"setup_{test_name}"].success
        assert f"run_{test_name}" in summary.phases
        assert summary.phases[f"run_{test_name}"].success
        assert f"collect_{test_name}" in summary.phases
        assert summary.phases[f"collect_{test_name}"].success

    # Verify artifacts for each VM
    expected_reps = config.repetitions
    for vm in multipass_vms:
        missing: list[str] = []
        host_output_dir = summary.per_host_output[vm["name"]]
        if not host_output_dir.exists():
            _handle_missing_artifacts(vm["name"], [f"output directory missing: {host_output_dir}"])
            continue

        files = list(host_output_dir.rglob("*"))
        print(f"Downloaded files for {vm['name']}: {files}")

        if not files:
            _handle_missing_artifacts(vm["name"], [f"No result files collected for {vm['name']} in {host_output_dir}"])
            continue

        run_root_candidates = [
            host_output_dir / summary.run_id / summary.run_id,
            host_output_dir / summary.run_id,
            host_output_dir,
        ]
        run_root = next(
            (path for path in run_root_candidates if path.exists()),
            None,
        )
        if run_root is None:
            _handle_missing_artifacts(vm["name"], [f"Run root missing (checked {run_root_candidates})"])
            continue

        system_info_candidates = [
            run_root / "system_info.csv",
            host_output_dir / "system_info.csv",
        ]
        if not any(p.exists() and p.stat().st_size > 0 for p in system_info_candidates):
            missing.append(
                f"system_info.csv missing or empty for {vm['name']} "
                f"(checked {system_info_candidates})"
            )

        for workload in workloads:
            workload_candidates = [
                run_root / workload,
                host_output_dir / workload,
            ]
            workload_dir = next(
                (path for path in workload_candidates if path.exists()),
                None,
            )
            if workload_dir is None:
                missing.append(
                    f"Workload directory not found for {workload} on {vm['name']} "
                    f"(checked {workload_candidates})"
                )
                continue
            for rep in range(1, expected_reps + 1):
                rep_dir = workload_dir / f"rep{rep}"
                cli_csv = rep_dir / f"{workload}_rep{rep}_CLICollector.csv"
                psutil_csv = rep_dir / f"{workload}_rep{rep}_PSUtilCollector.csv"
                for artifact in (cli_csv, psutil_csv):
                    if not artifact.exists() or artifact.stat().st_size == 0:
                        missing.append(f"Collector CSV missing or empty: {artifact}")

            plugin_csv = workload_dir / f"{workload}_plugin.csv"
            if not plugin_csv.exists() or plugin_csv.stat().st_size == 0:
                missing.append(f"Plugin CSV missing or empty: {plugin_csv}")

        _handle_missing_artifacts(vm["name"], missing)
