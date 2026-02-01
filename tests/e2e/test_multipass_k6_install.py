"""
Multipass e2e test for DFaaS k6 installation.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from tests.helpers.multipass import (
    ensure_ansible_available,
    ensure_multipass_access,
    inject_multipass_ssh_key,
    launch_multipass_vm,
    make_test_ansible_env,
    wait_for_multipass_ip,
)

pytestmark = [pytest.mark.inter_e2e, pytest.mark.inter_multipass, pytest.mark.slowest]


def _launch_vm(vm_name: str) -> None:
    launch_multipass_vm(
        vm_name,
        image_candidates=[
            os.environ.get("LB_MULTIPASS_IMAGE", "24.04"),
            os.environ.get("LB_MULTIPASS_FALLBACK_IMAGE", "lts"),
        ],
    )


def _write_inventory(inventory_path: Path, vm_name: str, ip_addr: str, key_path: Path) -> None:
    inventory_path.write_text(
        "[k6]\n"
        f"{vm_name} ansible_host={ip_addr} ansible_user=ubuntu "
        f"ansible_ssh_private_key_file={key_path} "
        "ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'\n"
    )


@pytest.mark.inter_generic
def test_multipass_k6_install(tmp_path: Path) -> None:
    """Install k6 on a fresh Multipass VM using the DFaaS playbook."""
    ensure_multipass_access()
    ensure_ansible_available()

    vm_name = f"lb-k6-install-{int(time.time())}"
    key_path = tmp_path / "lb_k6_key"
    pub_path = tmp_path / "lb_k6_key.pub"

    subprocess.run(["multipass", "delete", vm_name], stderr=subprocess.DEVNULL)
    subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)

    try:
        subprocess.run(
            ["ssh-keygen", "-t", "rsa", "-f", str(key_path), "-N", ""],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        _launch_vm(vm_name)
        ip_addr = wait_for_multipass_ip(vm_name)
        inject_multipass_ssh_key(vm_name, pub_path)

        inventory_path = tmp_path / "k6_hosts.ini"
        _write_inventory(inventory_path, vm_name, ip_addr, key_path)

        env = make_test_ansible_env(tmp_path)
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

        playbook = Path(__file__).resolve().parents[2] / "lb_plugins" / "plugins" / "dfaas" / "ansible" / "setup_k6.yml"
        subprocess.run(
            ["ansible-playbook", "-i", str(inventory_path), str(playbook)],
            cwd=tmp_path,
            env=env,
            check=True,
        )

        k6_check = subprocess.run(
            ["multipass", "exec", vm_name, "--", "k6", "version"],
            capture_output=True,
            text=True,
        )
        assert k6_check.returncode == 0
        assert "k6" in k6_check.stdout.lower()

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
