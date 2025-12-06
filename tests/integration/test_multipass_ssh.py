import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.integration.multipass_utils import ensure_ansible_available, make_test_ansible_env

REPO_ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_ROOT = REPO_ROOT / "linux_benchmark_lib" / "ansible"


def _multipass_available() -> bool:
    """Return True when the multipass CLI is present."""
    return shutil.which("multipass") is not None


def _wait_for_ip(vm_name: str, attempts: int = 10, delay: int = 2) -> str:
    """Poll multipass info until an IPv4 address is available."""
    for _ in range(attempts):
        proc = subprocess.run(
            ["multipass", "info", vm_name, "--format", "json"],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            info = json.loads(proc.stdout)
            ipv4 = info["info"][vm_name]["ipv4"]
            if ipv4:
                return ipv4[0]
        time.sleep(delay)
    raise RuntimeError(f"Failed to retrieve IP for {vm_name}")


def _inject_ssh_key(vm_name: str, pub_key_path: Path) -> None:
    """Copy the public key into the VM authorized_keys."""
    temp_remote = "/home/ubuntu/lb_test_key.pub"
    subprocess.run(
        ["multipass", "transfer", str(pub_key_path), f"{vm_name}:{temp_remote}"],
        check=True,
    )
    subprocess.run(
        [
            "multipass",
            "exec",
            vm_name,
            "--",
            "bash",
            "-c",
            "mkdir -p ~/.ssh "
            "&& cat ~/lb_test_key.pub >> ~/.ssh/authorized_keys "
            "&& chmod 600 ~/.ssh/authorized_keys "
            "&& rm ~/lb_test_key.pub",
        ],
        check=True,
    )


@pytest.mark.integration
def test_multipass_ssh_roundtrip(tmp_path: Path) -> None:
    """
    Minimal Multipass smoke test for SSH key provisioning.

    - Launch a fresh VM
    - Generate a throwaway keypair
    - Inject the public key
    - SSH in and run a simple command
    - Tear everything down (VM + key files)
    """
    if not _multipass_available():
        pytest.skip("Multipass not available on this host")

    vm_name = f"lb-ssh-test-{int(time.time())}"
    key_path = tmp_path / "lb_test_key"
    pub_path = tmp_path / "lb_test_key.pub"

    # Ensure we start from a clean VM name.
    subprocess.run(["multipass", "delete", vm_name], stderr=subprocess.DEVNULL)
    subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)

    try:
        # Generate keypair
        subprocess.run(
            ["ssh-keygen", "-t", "rsa", "-f", str(key_path), "-N", ""],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Launch VM (prefer image from env, fallback to 24.04 then lts)
        images = [
            os.environ.get("LB_MULTIPASS_IMAGE", "24.04"),
            os.environ.get("LB_MULTIPASS_FALLBACK_IMAGE", "lts"),
        ]
        for image in images:
            try:
                subprocess.run(
                    ["multipass", "launch", "--name", vm_name, image],
                    check=True,
                )
                break
            except subprocess.CalledProcessError:
                if image == images[-1]:
                    raise

        ip_addr = _wait_for_ip(vm_name)
        _inject_ssh_key(vm_name, pub_path)

        # SSH roundtrip
        ssh_cmd = [
            "ssh",
            "-i",
            str(key_path),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"ubuntu@{ip_addr}",
            "echo",
            "hello-from-multipass",
        ]
        ssh_proc = subprocess.run(
            ssh_cmd, check=True, capture_output=True, text=True
        )
        assert "hello-from-multipass" in ssh_proc.stdout

    finally:
        subprocess.run(
            ["multipass", "delete", vm_name, "--purge"],
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)
        for path in (key_path, pub_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


@pytest.mark.integration
def test_multipass_ansible_ping(tmp_path: Path) -> None:
    """
    End-to-end smoke test: provision VM, inject key, run Ansible ping.
    """
    if not _multipass_available():
        pytest.skip("Multipass not available on this host")
    ensure_ansible_available()

    vm_name = f"lb-ssh-test-{int(time.time())}"
    key_path = tmp_path / "lb_test_key"
    pub_path = tmp_path / "lb_test_key.pub"

    subprocess.run(["multipass", "delete", vm_name], stderr=subprocess.DEVNULL)
    subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)

    try:
        # Generate keypair
        subprocess.run(
            ["ssh-keygen", "-t", "rsa", "-f", str(key_path), "-N", ""],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Launch VM
        images = [
            os.environ.get("LB_MULTIPASS_IMAGE", "24.04"),
            os.environ.get("LB_MULTIPASS_FALLBACK_IMAGE", "lts"),
        ]
        for image in images:
            try:
                subprocess.run(
                    ["multipass", "launch", "--name", vm_name, image],
                    check=True,
                )
                break
            except subprocess.CalledProcessError:
                if image == images[-1]:
                    raise

        ip_addr = _wait_for_ip(vm_name)
        _inject_ssh_key(vm_name, pub_path)

        # Build inventory and playbook
        inventory_path = tmp_path / "hosts.ini"
        inventory_path.write_text(
            "[all]\n"
            f"{vm_name} ansible_host={ip_addr} ansible_user=ubuntu "
            f"ansible_ssh_private_key_file={key_path} "
            "ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'\n"
        )
        playbook_path = tmp_path / "ping.yml"
        playbook_path.write_text(
            "- hosts: all\n"
            "  gather_facts: false\n"
            "  tasks:\n"
            "    - name: Ping host\n"
            "      ansible.builtin.ping:\n"
        )

        # Run Ansible with controlled temp dirs
        env = make_test_ansible_env(tmp_path, roles_path=ANSIBLE_ROOT / "roles")

        subprocess.run(
            ["ansible-playbook", "-i", str(inventory_path), str(playbook_path)],
            cwd=tmp_path,
            env=env,
            check=True,
        )

    finally:
        subprocess.run(
            ["multipass", "delete", vm_name, "--purge"],
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)
        for path in (key_path, pub_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


@pytest.mark.integration
def test_multipass_ansible_stress_ng(tmp_path: Path) -> None:
    """
    Run a minimal stress-ng workload via Ansible on a fresh Multipass VM.
    """
    if not _multipass_available():
        pytest.skip("Multipass not available on this host")
    ensure_ansible_available()

    vm_name = f"lb-ssh-test-{int(time.time())}"
    key_path = tmp_path / "lb_test_key"
    pub_path = tmp_path / "lb_test_key.pub"

    subprocess.run(["multipass", "delete", vm_name], stderr=subprocess.DEVNULL)
    subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)

    try:
        subprocess.run(
            ["ssh-keygen", "-t", "rsa", "-f", str(key_path), "-N", ""],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        images = [
            os.environ.get("LB_MULTIPASS_IMAGE", "24.04"),
            os.environ.get("LB_MULTIPASS_FALLBACK_IMAGE", "lts"),
        ]
        for image in images:
            try:
                subprocess.run(
                    ["multipass", "launch", "--name", vm_name, image],
                    check=True,
                )
                break
            except subprocess.CalledProcessError:
                if image == images[-1]:
                    raise

        ip_addr = _wait_for_ip(vm_name)
        _inject_ssh_key(vm_name, pub_path)

        inventory_path = tmp_path / "hosts.ini"
        inventory_path.write_text(
            "[all]\n"
            f"{vm_name} ansible_host={ip_addr} ansible_user=ubuntu "
            f"ansible_ssh_private_key_file={key_path} "
            'ansible_ssh_common_args="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"\n'
        )
        playbook_path = tmp_path / "stress_ng.yml"
        playbook_path.write_text(
            "- hosts: all\n"
            "  become: true\n"
            "  gather_facts: true\n"
            "  tasks:\n"
            "    - name: Install stress-ng on Debian/Ubuntu\n"
            "      ansible.builtin.apt:\n"
            "        name: stress-ng\n"
            "        state: present\n"
            "        update_cache: true\n"
            "      when: ansible_os_family | default('') == 'Debian'\n"
            "    - name: Run short stress-ng\n"
            "      ansible.builtin.command: stress-ng --cpu 1 --timeout 3 --metrics-brief\n"
            "      register: stress_cmd\n"
            "      changed_when: false\n"
            "    - name: Ensure stress-ng succeeded\n"
            "      ansible.builtin.assert:\n"
            "        that:\n"
            "          - stress_cmd.rc == 0\n"
        )

        env = make_test_ansible_env(tmp_path, roles_path=ANSIBLE_ROOT / "roles")

        subprocess.run(
            ["ansible-playbook", "-i", str(inventory_path), str(playbook_path)],
            cwd=tmp_path,
            env=env,
            check=True,
        )

    finally:
        subprocess.run(
            ["multipass", "delete", vm_name, "--purge"],
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)
        for path in (key_path, pub_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


@pytest.mark.integration
def test_multipass_ansible_setup_playbook(tmp_path: Path) -> None:
    """
    Run the repo's setup playbook against a Multipass VM with controller-like extravars.
    """
    if not _multipass_available():
        pytest.skip("Multipass not available on this host")
    ensure_ansible_available()

    vm_name = f"lb-ssh-test-{int(time.time())}"
    key_path = tmp_path / "lb_test_key"
    pub_path = tmp_path / "lb_test_key.pub"

    subprocess.run(["multipass", "delete", vm_name], stderr=subprocess.DEVNULL)
    subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)

    try:
        subprocess.run(
            ["ssh-keygen", "-t", "rsa", "-f", str(key_path), "-N", ""],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        images = [
            os.environ.get("LB_MULTIPASS_IMAGE", "24.04"),
            os.environ.get("LB_MULTIPASS_FALLBACK_IMAGE", "lts"),
        ]
        for image in images:
            try:
                subprocess.run(
                    ["multipass", "launch", "--name", vm_name, image],
                    check=True,
                )
                break
            except subprocess.CalledProcessError:
                if image == images[-1]:
                    raise

        ip_addr = _wait_for_ip(vm_name)
        _inject_ssh_key(vm_name, pub_path)

        inventory_path = tmp_path / "hosts.ini"
        inventory_path.write_text(
            "[all]\n"
            f"{vm_name} ansible_host={ip_addr} ansible_user=ubuntu "
            f"ansible_ssh_private_key_file={key_path} "
            'ansible_ssh_common_args="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" '
            "ansible_become=true ansible_become_method=sudo\n"
        )

        # Mimic controller extravars
        run_id = "test_run"
        output_root = tmp_path / "results"
        report_root = tmp_path / "reports"
        export_root = tmp_path / "exports"
        extravars = {
            "run_id": run_id,
            "output_root": str(output_root),
            "remote_output_root": f"/tmp/benchmark_results/{run_id}",
            "report_root": str(report_root),
            "data_export_root": str(export_root),
            "lb_workdir": "/opt/lb",
            "per_host_output": {vm_name: str(output_root / vm_name)},
            "benchmark_config": {},  # Not used by setup.yml today
            "use_container_fallback": False,
            "workload_runner_install_deps": False,
            "collector_apt_packages": ["stress-ng"],
            "_lb_inventory_path": str(inventory_path),
        }
        extravars_path = tmp_path / "extravars.json"
        extravars_path.write_text(json.dumps(extravars))

        env = make_test_ansible_env(tmp_path, roles_path=ANSIBLE_ROOT / "roles")

        setup_playbook = (ANSIBLE_ROOT / "playbooks" / "setup.yml").absolute()
        subprocess.run(
            [
                "ansible-playbook",
                "-i",
                str(inventory_path),
                "-e",
                f"@{extravars_path}",
                str(setup_playbook),
            ],
            cwd=tmp_path,
            env=env,
            check=True,
        )

        # Post-check: verify that venv and project files exist on the VM.
        ssh_cmd = [
            "ssh",
            "-i",
            str(key_path),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"ubuntu@{ip_addr}",
            "test -x /opt/lb/.venv/bin/python && test -f /opt/lb/linux_benchmark_lib/cli.py",
        ]
        subprocess.run(ssh_cmd, check=True)

        # Run the workload runner playbook for stress_ng (smoke: single test).
        extravars["tests"] = ["stress_ng"]
        extravars["benchmark_config"] = {
            "workloads": {
                "stress_ng": {
                    "plugin": "stress_ng", 
                    "enabled": True, 
                    "options": {"vm_workers": 0, "cpu_workers": 1, "timeout": 3, "metrics_brief": True}
                }
            },
            "plugin_settings": {},
            "repetitions": 1,
            "test_duration_seconds": 3,
            "warmup_seconds": 0,
            "cooldown_seconds": 0,
            "output_dir": str(output_root),
            "report_dir": str(report_root),
            "data_export_dir": str(export_root),
        }
        extravars_path.write_text(json.dumps(extravars))

        subprocess.run(
            [
                "ansible-playbook",
                "-i",
                str(inventory_path),
                "-e",
                f"@{extravars_path}",
                str((ANSIBLE_ROOT / "playbooks" / "run_benchmark.yml").absolute()),
            ],
            cwd=tmp_path,
            env=env,
            check=True,
        )

    finally:
        subprocess.run(
            ["multipass", "delete", vm_name, "--purge"],
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)
        for path in (key_path, pub_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
