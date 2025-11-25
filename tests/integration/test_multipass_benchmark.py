import json
import os
import shutil
import subprocess
import time
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
from tests.integration.multipass_utils import get_intensity

# Constants
VM_NAME_PREFIX = "benchmark-test-vm"
MAX_VM_COUNT = 2
SSH_KEY_PATH = Path("./test_key")
SSH_PUB_KEY_PATH = Path("./test_key.pub")

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
            subprocess.run(["multipass", "launch", "--name", vm_name, image], check=True)
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

    workloads = os.environ.get("LB_MULTIPASS_WORKLOADS", "stress_ng").split(",")
    workloads = [w.strip() for w in workloads if w.strip()]

    # Create configuration
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

    # Add workload configs if enabled
    if "stress_ng" in workloads:
        config_args["stress_ng"] = StressNGConfig(
            cpu_workers=1,
            timeout=intensity["stress_timeout"]
        )
    
    if "dd" in workloads:
        config_args["dd"] = DDConfig(
            bs="1M", 
            count=intensity["dd_count"], 
            of_path="/tmp/dd_test"
        )

    if "fio" in workloads:
        config_args["fio"] = FIOConfig(
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

    # Note: iperf3 and others can be added here similarly if needed

    config = BenchmarkConfig(**config_args)

    # Use a separate temp dir for ansible runner data
    ansible_dir = tmp_path / "ansible_data"
    
    # Ensure Ansible finds roles and config
    os.environ["ANSIBLE_ROLES_PATH"] = str(Path("ansible/roles").absolute())
    os.environ["ANSIBLE_CONFIG"] = str(Path("ansible/ansible.cfg").absolute())
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    
    executor = AnsibleRunnerExecutor(private_data_dir=ansible_dir, stream_output=True)
    controller = BenchmarkController(config, executor=executor)

    # Execute
    print(f"Starting benchmark controller for workloads: {workloads}")
    summary = controller.run(workloads, run_id="test_run")

    # Verify execution
    assert summary.success, f"Benchmark failed. Phases: {summary.phases}"
    assert "setup" in summary.phases
    assert summary.phases["setup"].success
    assert "run" in summary.phases
    assert summary.phases["run"].success
    assert "collect" in summary.phases
    assert summary.phases["collect"].success

    # Verify artifacts for each VM
    for vm in multipass_vms:
        host_output_dir = summary.per_host_output[vm["name"]]
        assert host_output_dir.exists()

        files = list(host_output_dir.rglob("*"))
        print(f"Downloaded files for {vm['name']}: {files}")

        assert files, f"No result files were collected for {vm['name']}."
