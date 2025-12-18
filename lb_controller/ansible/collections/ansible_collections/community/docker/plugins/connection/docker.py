"""Lightweight docker connection plugin, aligned with community.docker.docker."""

from __future__ import annotations

import os
import subprocess
from typing import Any, Tuple

from ansible.errors import AnsibleError
from ansible.plugins.connection import ConnectionBase

DOCUMENTATION = r"""
connection: docker
short_description: Run tasks inside Docker containers
description:
  - Connect to existing containers using C(docker exec) and copy files with C(docker cp).
author: Generated for linux-benchmark-lib
version_added: "1.0"
options: {}
"""


class Connection(ConnectionBase):
    """Executes commands inside a running container via docker exec/cp."""

    transport = "docker"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.container_name = self._play_context.remote_addr

    def _connect(self) -> None:
        if not self.container_name:
            raise AnsibleError("docker connection requires a container name")
        self._connected = True
        return None

    def exec_command(
        self, cmd: str, in_data: Any | None = None, sudoable: bool = False
    ) -> Tuple[int, str, str]:
        command = ["docker", "exec", self.container_name, "bash", "-c", cmd]
        try:
            result = subprocess.run(
                command,
                input=in_data,
                text=False if in_data is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise AnsibleError("docker CLI not found in PATH") from exc
        return result.returncode, result.stdout.decode(), result.stderr.decode()

    def put_file(self, in_path: str, out_path: str) -> None:
        command = ["docker", "cp", in_path, f"{self.container_name}:{out_path}"]
        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            raise AnsibleError(
                f"Failed to copy {in_path} to {out_path}: {exc.stderr.decode()}"
            ) from exc

    def fetch_file(self, in_path: str, out_path: str) -> None:
        target_dir = os.path.dirname(out_path) or "."
        os.makedirs(target_dir, exist_ok=True)
        command = ["docker", "cp", f"{self.container_name}:{in_path}", out_path]
        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            raise AnsibleError(
                f"Failed to fetch {in_path} to {out_path}: {exc.stderr.decode()}"
            ) from exc
