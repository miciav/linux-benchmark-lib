import pytest
import subprocess
import json
import time
import os
import shutil
from pathlib import Path
from benchmark_config import BenchmarkConfig, RemoteHostConfig, RemoteExecutionConfig, StressNGConfig
from orchestrator import BenchmarkOrchestrator, AnsibleRunnerExecutor

# Constants
VM_NAME = "benchmark-test-vm"
SSH_KEY_PATH = Path("./test_key")
SSH_PUB_KEY_PATH = Path("./test_key.pub")

def is_multipass_available():
    """Check if multipass is installed and available."""
    return shutil.which("multipass") is not None

@pytest.fixture(scope="module")
def multipass_vm():
    """
    Fixture to provision a Multipass VM for testing.
    It generates an SSH key, launches a VM, injects the key, and yields connection info.
    """
    if not is_multipass_available():
        pytest.skip("Multipass not found. Skipping integration test.")

    # Generate SSH key pair if not exists
    if not SSH_KEY_PATH.exists():
        subprocess.run(
            ["ssh-keygen", "-t", "rsa", "-f", str(SSH_KEY_PATH), "-N", ""],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    pub_key = SSH_PUB_KEY_PATH.read_text().strip()

    # Launch VM (using lts image)
    print(f"Launching multipass VM: {VM_NAME}...")
    # Check if exists, delete if so
    subprocess.run(["multipass", "delete", VM_NAME], stderr=subprocess.DEVNULL)
    subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)
    
    try:
        subprocess.run(["multipass", "launch", "--name", VM_NAME, "lts"], check=True)
        
        # Wait for VM to be ready and get IP
        # Sometimes IP takes a moment
        for _ in range(10):
            info_proc = subprocess.run(
                ["multipass", "info", VM_NAME, "--format", "json"],
                capture_output=True,
                text=True
            )
            if info_proc.returncode == 0:
                info = json.loads(info_proc.stdout)
                ipv4 = info["info"][VM_NAME]["ipv4"]
                if ipv4:
                    ip_address = ipv4[0]
                    break
            time.sleep(2)
        else:
            pytest.fail("Could not retrieve VM IP address.")

        print(f"VM started at {ip_address}. Injecting SSH key...")
        
        # Inject SSH key with retries
        cmd = f"mkdir -p ~/.ssh && echo '{pub_key}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
        
        for i in range(10):
            try:
                subprocess.run(["multipass", "exec", VM_NAME, "--", "bash", "-c", cmd], check=True)
                break
            except subprocess.CalledProcessError:
                if i == 9:
                    raise
                print(f"SSH injection failed, retrying ({i+1}/10)...")
                time.sleep(3)

        yield {
            "name": VM_NAME,
            "ip": ip_address,
            "user": "ubuntu",
            "key_path": SSH_KEY_PATH.absolute()
        }

    finally:
        # Teardown
        print(f"Tearing down VM: {VM_NAME}...")
        subprocess.run(["multipass", "delete", VM_NAME, "--purge"], stderr=subprocess.DEVNULL)
        # Remove generated SSH keys if present
        for key_path in (SSH_KEY_PATH, SSH_PUB_KEY_PATH):
            try:
                key_path.unlink()
            except FileNotFoundError:
                pass
        if SSH_KEY_PATH.exists():
            SSH_KEY_PATH.unlink()
        if SSH_PUB_KEY_PATH.exists():
            SSH_PUB_KEY_PATH.unlink()

def test_remote_benchmark_execution(multipass_vm, tmp_path):
    """
    Test the full remote benchmark execution flow on a Multipass VM.
    """
    base_dir = Path(os.environ.get("LB_TEST_RESULTS_DIR", tmp_path))
    output_dir = base_dir / "results"
    report_dir = base_dir / "reports"
    export_dir = base_dir / "exports"

    # Create configuration
    host_config = RemoteHostConfig(
        name=multipass_vm["name"],
        address=multipass_vm["ip"],
        user=multipass_vm["user"],
        become=True,
        vars={
            "ansible_ssh_private_key_file": str(multipass_vm["key_path"]),
            "ansible_ssh_common_args": "-o StrictHostKeyChecking=no"
        }
    )

    # Run a very short stress-ng test
    config = BenchmarkConfig(
        output_dir=output_dir,
        report_dir=report_dir,
        data_export_dir=export_dir,
        remote_hosts=[host_config],
        remote_execution=RemoteExecutionConfig(
            enabled=True,
            run_setup=True,
            run_collect=True
        ),
        stress_ng=StressNGConfig(
            cpu_workers=1,
            timeout=5  # Short timeout for test
        )
    )

    # Use a separate temp dir for ansible runner data
    ansible_dir = tmp_path / "ansible_data"
    
    # Ensure Ansible finds roles and config
    os.environ["ANSIBLE_ROLES_PATH"] = str(Path("ansible/roles").absolute())
    os.environ["ANSIBLE_CONFIG"] = str(Path("ansible/ansible.cfg").absolute())
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    
    executor = AnsibleRunnerExecutor(private_data_dir=ansible_dir, stream_output=True)
    orchestrator = BenchmarkOrchestrator(config, executor=executor)

    # Execute
    print("Starting benchmark orchestrator...")
    summary = orchestrator.run(["stress_ng"], run_id="test_run")

    # Verify execution
    assert summary.success, f"Benchmark failed. Phases: {summary.phases}"
    assert "setup" in summary.phases
    assert summary.phases["setup"].success
    assert "run" in summary.phases
    assert summary.phases["run"].success
    assert "collect" in summary.phases
    assert summary.phases["collect"].success

    # Verify artifacts
    host_output_dir = summary.per_host_output[VM_NAME]
    assert host_output_dir.exists()
    
    # Check if result files were downloaded
    # There should be a structure like <host_output_dir>/benchmark_results/...
    # The exact structure depends on the collector role, but we expect *some* files.
    # 'collect.yml' usually fetches the whole output directory.
    
    # List files to debug if needed
    files = list(host_output_dir.rglob("*"))
    print(f"Downloaded files: {files}")
    
    assert len(files) > 0, "No result files were collected."
