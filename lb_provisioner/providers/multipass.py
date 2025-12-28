"""Provision Multipass VMs and expose them as Ansible hosts."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import List

from lb_common.api import RemoteHostSpec

from lb_provisioner.models.types import (
    MAX_NODES,
    ProvisionedNode,
    ProvisioningError,
    ProvisioningRequest,
)

logger = logging.getLogger(__name__)


class MultipassProvisioner:
    """Manage ephemeral Multipass VMs."""

    def __init__(self, base_state_dir: Path | None = None):
        self.base_state_dir = base_state_dir or Path(
            tempfile.gettempdir()
        ) / "lb_multipass"
        self.base_state_dir.mkdir(parents=True, exist_ok=True)

    def provision(self, request: ProvisioningRequest) -> List[ProvisionedNode]:
        """Provision up to MAX_NODES Multipass instances."""
        if not shutil.which("multipass"):
            raise ProvisioningError("Multipass CLI not found in PATH")

        if request.node_names:
            names = list(request.node_names)
            count = len(names)
        else:
            names = []
            count = max(1, min(request.count, MAX_NODES))
        nodes: List[ProvisionedNode] = []
        state_root = request.state_dir or self.base_state_dir
        state_root.mkdir(parents=True, exist_ok=True)

        for idx in range(count):
            vm_name = names[idx] if names else f"lb-worker-{uuid.uuid4().hex[:8]}"
            key_path = state_root / f"{vm_name}_id_rsa"
            pub_path = state_root / f"{vm_name}_id_rsa.pub"
            self._generate_ephemeral_keys(key_path)
            self._launch_vm(vm_name, request.multipass_image)
            ip = self._get_ip_address(vm_name)
            self._inject_ssh_key(vm_name, pub_path)
            host = RemoteHostSpec(
                name=vm_name,
                address=ip,
                user="ubuntu",
                become=True,
                vars={
                    "ansible_ssh_private_key_file": str(key_path.absolute()),
                    "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
                    "ansible_python_interpreter": "/usr/bin/python3",
                },
            )
            nodes.append(
                ProvisionedNode(
                    host=host,
                    destroy=lambda name=vm_name, kp=key_path, pp=pub_path: self._destroy_vm(
                        name, kp, pp
                    ),
                )
            )
        return nodes

    def _generate_ephemeral_keys(self, key_path: Path) -> None:
        """Generate a fresh SSH key pair."""
        try:
            subprocess.run(
                [
                    "ssh-keygen",
                    "-t",
                    "rsa",
                    "-b",
                    "4096",
                    "-f",
                    str(key_path),
                    "-N",
                    "",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            key_path.chmod(0o600)
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            raise ProvisioningError(
                f"Failed to generate SSH key: {exc.stderr.decode()}"
            ) from exc

    def _launch_vm(self, vm_name: str, image: str) -> None:
        """Launch a Multipass VM."""
        cmd = [
            "multipass",
            "launch",
            image,
            "--name",
            vm_name,
            "--cpus",
            "4",
            "--disk",
            "20G",
            "--memory",
            "8G",
        ]
        logger.info("Launching Multipass VM %s (%s)", vm_name, image)
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            fallback = cmd[:]
            fallback[2] = "lts"
            try:
                subprocess.run(
                    fallback, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
                raise ProvisioningError(f"Failed to launch VM {vm_name}: {exc}") from exc

    def _get_ip_address(self, vm_name: str) -> str:
        """Return the IPv4 address for the VM, waiting until assigned."""
        for _ in range(15):
            try:
                result = subprocess.run(
                    ["multipass", "info", vm_name, "--format", "json"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                info = json.loads(result.stdout)
                ipv4_list = info.get("info", {}).get(vm_name, {}).get("ipv4", [])
                if ipv4_list:
                    return ipv4_list[0]
            except Exception:
                time.sleep(2)
                continue
            time.sleep(2)
        raise ProvisioningError(f"Timed out waiting for IP of {vm_name}")

    def _inject_ssh_key(self, vm_name: str, pub_path: Path) -> None:
        """Inject the generated SSH key into the VM."""
        if not pub_path.exists():
            raise ProvisioningError("Public key not found for SSH injection")

        content = pub_path.read_text().strip()
        script = (
            "mkdir -p ~/.ssh && "
            f"echo '{content}' >> ~/.ssh/authorized_keys && "
            "chmod 600 ~/.ssh/authorized_keys && "
            "chmod 700 ~/.ssh"
        )
        try:
            subprocess.run(
                ["multipass", "exec", vm_name, "--", "bash", "-c", script],
                check=True,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            raise ProvisioningError(
                f"Failed to inject SSH key for {vm_name}: {exc.stderr.decode()}"
            ) from exc

    def _destroy_vm(self, vm_name: str, key_path: Path, pub_path: Path) -> None:
        """Destroy VM and wipe associated SSH keys."""
        try:
            subprocess.run(
                ["multipass", "delete", vm_name, "--purge"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            logger.debug("Best-effort cleanup failed for VM %s", vm_name)

        for path in (key_path, pub_path):
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                logger.debug("Failed to remove %s", path)
