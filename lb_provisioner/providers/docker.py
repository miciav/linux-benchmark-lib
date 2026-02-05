"""Provision nodes using local Docker/Podman containers."""

from __future__ import annotations

import logging
import shutil
import subprocess
import socket
import time
import uuid
from typing import List
from pathlib import Path

from lb_common.api import RemoteHostSpec

from lb_provisioner.models.types import (
    MAX_NODES,
    ProvisionedNode,
    ProvisioningError,
    ProvisioningRequest,
)

logger = logging.getLogger(__name__)


class DockerProvisioner:
    """Create ephemeral containers and expose them as Ansible hosts."""

    def provision(self, request: ProvisioningRequest) -> List[ProvisionedNode]:
        """Provision up to MAX_NODES containers."""
        engine = request.docker_engine
        if not shutil.which(engine):
            raise ProvisioningError(f"{engine} not found in PATH")

        if request.node_names:
            names = list(request.node_names)
            count = len(names)
        else:
            names = []
            count = max(1, min(request.count, MAX_NODES))
        state_root = request.state_dir or Path("/tmp/lb_docker_keys")
        state_root.mkdir(parents=True, exist_ok=True)
        nodes: List[ProvisionedNode] = []
        for idx in range(count):
            if names:
                name = names[idx]
            else:
                name = f"lb-docker-{uuid.uuid4().hex[:8]}-{idx}"
            key_path = state_root / f"{name}_id_rsa"
            pub_path = state_root / f"{name}_id_rsa.pub"
            self._generate_ssh_keypair(key_path)
            port = self._find_free_port()
            self._run_container(engine, request.docker_image, name, port)
            self._inject_ssh_key(engine, name, pub_path)
            self._wait_for_ssh(engine, name, port, key_path)
            host = RemoteHostSpec(
                name=name,
                address="127.0.0.1",
                user="root",
                become=True,
                port=port,
                vars={
                    "ansible_ssh_private_key_file": str(key_path),
                    "ansible_ssh_common_args": (
                        "-o StrictHostKeyChecking=no "
                        "-o UserKnownHostsFile=/dev/null"
                    ),
                    "ansible_python_interpreter": "/usr/bin/python3",
                    "lb_is_container": True,
                },
            )
            def _destroy(
                eng: str = engine,
                cname: str = name,
                kp: Path = key_path,
                pp: Path = pub_path,
            ) -> None:
                self._destroy_container(eng, cname, kp, pp)

            nodes.append(
                ProvisionedNode(
                    host=host,
                    destroy=_destroy,
                )
            )
        return nodes

    def _generate_ssh_keypair(self, key_path: Path) -> None:
        """Generate an RSA keypair for SSH access."""
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

    def _find_free_port(self) -> int:
        """Return an available host port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", 0))
            return sock.getsockname()[1]

    def _run_container(
        self, engine: str, image: str, name: str, host_port: int
    ) -> None:
        """Start a detached container with SSHD running."""
        init_script = (
            "apt-get update -qq && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "openssh-server sudo python3 && "
            "mkdir -p /var/run/sshd && "
            "sed -i -E 's@^#?PasswordAuthentication.*@PasswordAuthentication no@' "
            "/etc/ssh/sshd_config && "
            "sed -i -E 's@^#?PermitRootLogin.*@PermitRootLogin prohibit-password@' "
            "/etc/ssh/sshd_config && "
            "ssh-keygen -A && "
            "/usr/sbin/sshd -D"
        )
        cmd = [
            engine,
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--hostname",
            name,
            "-p",
            f"{host_port}:22",
            image,
            "bash",
            "-c",
            init_script,
        ]
        logger.info("Provisioning container %s via %s", name, engine)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            raise ProvisioningError(
                f"Failed to start container {name}: {stderr or stdout}"
            ) from exc

    def _inject_ssh_key(self, engine: str, name: str, pub_path: Path) -> None:
        """Inject the generated public key into root authorized_keys."""
        content = pub_path.read_text().strip()
        script = (
            "mkdir -p /root/.ssh && "
            f"echo '{content}' >> /root/.ssh/authorized_keys && "
            "chmod 600 /root/.ssh/authorized_keys && "
            "chmod 700 /root/.ssh"
        )
        cmd = [engine, "exec", name, "bash", "-c", script]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            raise ProvisioningError(
                f"Failed to inject SSH key into {name}: {exc.stderr}"
            ) from exc

    def _wait_for_ssh(
        self,
        engine: str,
        name: str,
        port: int,
        key_path: Path,
        retries: int = 60,
        delay: float = 2.0,
    ) -> None:
        """Poll until the container's SSH service accepts connections."""
        cmd = [
            "ssh",
            "-i",
            str(key_path),
            "-p",
            str(port),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=5",
            "root@127.0.0.1",
            "true",
        ]
        # Give the SSH daemon a brief head-start before polling.
        time.sleep(1.5)
        for attempt in range(retries):
            if not self._container_running(engine, name):
                logs = self._container_logs(engine, name)
                raise ProvisioningError(
                    f"Container {name} exited before SSH became reachable. "
                    f"Logs:\n{logs}"
                )
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0:
                return
            time.sleep(delay)
        logs = self._container_logs(engine, name)
        raise ProvisioningError(
            f"SSH not reachable on 127.0.0.1:{port} after {retries} attempts. "
            f"Logs:\n{logs}"
        )

    @staticmethod
    def _container_running(engine: str, name: str) -> bool:
        cmd = [engine, "inspect", "-f", "{{.State.Running}}", name]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except Exception:
            return False
        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    @staticmethod
    def _container_logs(engine: str, name: str, tail: int = 50) -> str:
        cmd = [engine, "logs", "--tail", str(tail), name]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except Exception:
            return "<unable to fetch logs>"
        output = (result.stdout or "") + (result.stderr or "")
        return output.strip() or "<no logs>"

    def _destroy_container(
        self, engine: str, name: str, key_path: Path, pub_path: Path
    ) -> None:
        """Stop and remove a container and its keys; ignore failures."""
        cmd = [engine, "rm", "-f", name]
        try:
            subprocess.run(
                cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            logger.debug("Best-effort cleanup failed for container %s", name)
        for path in (key_path, pub_path):
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                logger.debug("Failed to remove %s", path)
