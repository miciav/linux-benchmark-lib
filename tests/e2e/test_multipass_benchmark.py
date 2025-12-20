import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
# import multiprocessing # Removed for multiprocessing context fix

import pytest

# Explicitly set the start method for multiprocessing on macOS
# This can help with issues related to ansible-runner's worker processes
# try:
#     multiprocessing.set_start_method('fork', force=True)
# except RuntimeError:
#     pass # Already set, or not supported on this platform/context

pytestmark = [pytest.mark.e2e, pytest.mark.multipass, pytest.mark.slowest]

REPO_ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_ROOT = REPO_ROOT / "lb_controller" / "ansible"

from lb_runner.benchmark_config import (
    BenchmarkConfig,
    MetricCollectorConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_runner.plugins.dd.plugin import DDConfig
from lb_runner.plugins.stress_ng.plugin import StressNGConfig
from lb_controller.ansible_executor import AnsibleRunnerExecutor
from lb_controller.api import BenchmarkController
from tests.helpers.multipass import (
    get_intensity,
    make_test_ansible_env,
    stage_private_key,
)
from lb_runner.plugins.fio.plugin import FIOConfig

# Constants
VM_NAME_PREFIX = "benchmark-test-vm"
MAX_VM_COUNT = 2
SSH_KEY_PATH = Path("./temp_keys/test_key")
SSH_PUB_KEY_PATH = Path("./temp_keys/test_key.pub")
DEFAULT_VM_CPUS = 2
DEFAULT_VM_MEMORY = "2G"
DEFAULT_VM_DISK = "10G"

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

def _vm_name(index: int, total: int) -> str:
    if total == 1:
        return VM_NAME_PREFIX
    return f"{VM_NAME_PREFIX}-{index + 1}"

def _wait_for_ip(vm_name: str) -> str:
    for _ in range(10):
        info_proc = subprocess.run(
            ["multipass", "info", vm_name, "--format", "json"],
            capture_output=True,
            text=True,
        )
        if info_proc.returncode == 0:
            info = json.loads(info_proc.stdout)
            ipv4 = info["info"][vm_name]["ipv4"]
            if ipv4:
                return ipv4[0]
        time.sleep(2)
    pytest.fail(f"Could not retrieve VM IP address for {vm_name}.")

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
    tried = []
    for image in [primary, fallback]:
        if image in tried:
            continue
        tried.append(image)
        try:
            subprocess.run(
                [
                    "multipass",
                    "launch",
                    "--name",
                    vm_name,
                    "--cpus",
                    str(_vm_cpus()),
                    "--memory",
                    _vm_memory(),
                    "--disk",
                    _vm_disk(),
                    image,
                ],
                check=True,
            )
            break
        except subprocess.CalledProcessError:
            print(f"Image '{image}' failed to launch, trying next option...")
            if image == tried[-1] and len(tried) == 2:
                raise
    ip_address = _wait_for_ip(vm_name)
    print(f"VM {vm_name} started at {ip_address}. Injecting SSH key...")
    _inject_ssh_key(vm_name, pub_key)
    return {
        "name": vm_name,
        "ip": ip_address,
        "user": "ubuntu",
        "key_path": SSH_KEY_PATH.absolute(),
    }

@pytest.fixture(scope="module")
def multipass_vm():
    """
    Fixture to provision one or more Multipass VMs for testing.
    It generates an SSH key, launches the requested VMs, injects the key, and yields
    connection info.
    """
    if not is_multipass_available():
        pytest.skip("Multipass not found. Skipping integration test.")

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
        subprocess.run(["multipass", "delete", name], stderr=subprocess.DEVNULL)
    subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)

    created_vms = []
    try:
        for name in vm_names:
            created_vms.append(_launch_vm(name, pub_key))

        yield created_vms

    finally:
        # Teardown
        for vm in created_vms:
            print(f"Tearing down VM: {vm['name']}...")
            subprocess.run(
                ["multipass", "delete", vm["name"], "--purge"],
                stderr=subprocess.DEVNULL,
            )
        subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)
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
            enabled=True,
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
            enabled=True,
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
            enabled=True,
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
    controller = BenchmarkController(config, executor=executor)

    # Execute
    print(f"Starting benchmark controller for workloads: {workloads}")
    summary = controller.run(workloads, run_id="test_run")

    # Verify execution
    assert summary.success, f"Benchmark failed. Phases: {summary.phases}"
    # Phases: setup_global + per-test phases + collect
    assert "setup_global" in summary.phases and summary.phases["setup_global"].success
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
        host_output_dir = summary.per_host_output[vm["name"]]
        assert host_output_dir.exists()

        files = list(host_output_dir.rglob("*"))
        print(f"Downloaded files for {vm['name']}: {files}")

        assert files, f"No result files were collected for {vm['name']}."
        run_root_candidates = [
            host_output_dir / summary.run_id / summary.run_id,
            host_output_dir / summary.run_id,
            host_output_dir,
        ]
        run_root = next(
            (path for path in run_root_candidates if path.exists()),
            None,
        )
        assert run_root is not None, (
            f"Run root missing for {vm['name']} "
            f"(checked {run_root_candidates})"
        )

        system_info_candidates = [
            run_root / "system_info.csv",
            host_output_dir / "system_info.csv",
        ]
        assert any(
            p.exists() and p.stat().st_size > 0 for p in system_info_candidates
        ), (
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
            assert workload_dir is not None, (
                f"Workload directory not found for {workload} on {vm['name']} "
                f"(checked {workload_candidates})"
            )
            for rep in range(1, expected_reps + 1):
                cli_csv = workload_dir / f"{workload}_rep{rep}_CLICollector.csv"
                psutil_csv = workload_dir / f"{workload}_rep{rep}_PSUtilCollector.csv"
                for artifact in (cli_csv, psutil_csv):
                    assert artifact.exists(), f"Missing collector CSV {artifact}"
                    assert artifact.stat().st_size > 0, (
                        f"Collector CSV is empty: {artifact}"
                    )

            plugin_csv = workload_dir / f"{workload}_plugin.csv"
            assert plugin_csv.exists(), f"Missing plugin CSV {plugin_csv}"
            assert plugin_csv.stat().st_size > 0, (
                f"Plugin CSV is empty: {plugin_csv}"
            )
