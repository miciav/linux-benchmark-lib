"""Ansible-based remote executor implementation."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lb_controller.types import ExecutionResult, InventorySpec, RemoteExecutor

logger = logging.getLogger(__name__)
ANSIBLE_ROOT = Path(__file__).resolve().parent / "ansible"


class AnsibleRunnerExecutor(RemoteExecutor):
    """Remote executor implemented with ansible-runner."""

    def __init__(
        self,
        private_data_dir: Optional[Path] = None,
        runner_fn: Optional[Callable[..., Any]] = None,
        stream_output: bool = False,
        output_callback: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Initialize the executor.

        Args:
            private_data_dir: Directory used by ansible-runner.
            runner_fn: Optional runner callable for testing. Defaults to
                ansible_runner.run when not provided.
            stream_output: When True, stream Ansible stdout events to the local
                process (useful for visibility in long-running tasks).
            output_callback: Optional callback to handle stdout stream.
                             Signature: (text: str, end: str) -> None
        """
        self.private_data_dir = private_data_dir or Path(".ansible_runner")
        self.private_data_dir.mkdir(parents=True, exist_ok=True)
        self.event_log_path = self.private_data_dir / "lb_events.jsonl"
        self._runner_fn = runner_fn
        self.stream_output = stream_output
        # Force Ansible temp into a writable location inside the runner dir to avoid host-level permission issues
        self.local_tmp = self.private_data_dir / "tmp"
        self.local_tmp.mkdir(parents=True, exist_ok=True)
        if stream_output and output_callback is None:
            # Default to streaming to stdout when caller requests streaming but
            # doesn't provide a handler.
            def _default_cb(text: str, end: str = "") -> None:
                sys.stdout.write(text + end)
                sys.stdout.flush()

            self.output_callback = _default_cb
        else:
            self.output_callback = output_callback

    def run_playbook(
        self,
        playbook_path: Path,
        inventory: InventorySpec,
        extravars: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        limit_hosts: Optional[List[str]] = None,
    ) -> ExecutionResult:
        """Execute a playbook using ansible-runner."""
        if not playbook_path.exists():
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")

        inventory_path = self._prepare_inventory(inventory)
        runner_fn = self._runner_fn or self._import_runner()

        # Ensure playbook path is absolute so runner can find it
        # regardless of private_data_dir location
        abs_playbook_path = playbook_path.resolve()

        logger.info(
            "Running playbook %s against %d host(s)",
            abs_playbook_path,
            len(inventory.hosts),
        )

        merged_extravars = extravars.copy() if extravars else {}
        merged_extravars.setdefault("_lb_inventory_path", str(inventory_path))

        repo_roles = (ANSIBLE_ROOT / "roles").resolve()
        runner_roles = (self.private_data_dir / "roles").resolve()
        callback_dir = (ANSIBLE_ROOT / "callback_plugins").resolve()
        envvars = {
            "ANSIBLE_ROLES_PATH": f"{runner_roles}:{repo_roles}",
            "ANSIBLE_LOCAL_TEMP": str(self.local_tmp),
            "ANSIBLE_REMOTE_TMP": "/tmp/.ansible",
            "ANSIBLE_CONFIG": str((ANSIBLE_ROOT / "ansible.cfg").resolve()),
            # Use default callback; debug tasks echo LB_EVENT markers.
            "ANSIBLE_STDOUT_CALLBACK": "default",
            "ANSIBLE_CALLBACK_PLUGINS": str(callback_dir),
            "ANSIBLE_CALLBACKS_ENABLED": "lb_events",
            "LB_EVENT_LOG_PATH": str(self.event_log_path),
        }

        if self._runner_fn:
            result = runner_fn(
                private_data_dir=str(self.private_data_dir),
                playbook=str(abs_playbook_path),
                inventory=str(inventory_path.resolve()),
                extravars=merged_extravars,
                tags=",".join(tags) if tags else None,
                envvars=envvars,
                limit=",".join(limit_hosts) if limit_hosts else None,
            )
        else:
            result = self._run_subprocess_playbook(
                abs_playbook_path=abs_playbook_path,
                inventory_path=inventory_path,
                extravars=merged_extravars,
                tags=tags,
                envvars=envvars,
                limit_hosts=limit_hosts,
            )

        rc = getattr(result, "rc", 1)
        status = getattr(result, "status", "failed")
        stats = getattr(result, "stats", {}) or {}
        logger.info(
            "Playbook %s finished with rc=%s status=%s",
            playbook_path,
            rc,
            status,
        )
        return ExecutionResult(rc=rc, status=status, stats=stats)

    def _prepare_inventory(self, inventory: InventorySpec) -> Path:
        """Write a transient inventory file or return the provided one."""
        if inventory.inventory_path:
            if not inventory.inventory_path.exists():
                raise FileNotFoundError(
                    f"Inventory file not found: {inventory.inventory_path}"
                )
            return inventory.inventory_path

        inventory_dir = self.private_data_dir / "inventory"
        inventory_dir.mkdir(parents=True, exist_ok=True)
        inventory_file = inventory_dir / "hosts.ini"
        inventory_file.write_text(_render_inventory(inventory.hosts))
        return inventory_file

    @staticmethod
    def _import_runner() -> Callable[..., Any]:
        """Import ansible_runner lazily to avoid hard dependency at import time."""
        try:
            import ansible_runner  # type: ignore
        except ImportError as exc:  # pragma: no cover - guarded at runtime
            raise RuntimeError(
                "ansible-runner is required for remote execution. "
                "Install it with `uv pip install ansible-runner`."
            ) from exc
        return ansible_runner.run

    def _run_subprocess_playbook(
        self,
        abs_playbook_path: Path,
        inventory_path: Path,
        extravars: Dict[str, Any],
        tags: Optional[List[str]],
        envvars: Dict[str, str],
        limit_hosts: Optional[List[str]] = None,
    ) -> ExecutionResult:
        """
        Execute ansible-playbook via subprocess to avoid ansible-runner's awx_display callback.
        """
        cmd = [
            "ansible-playbook",
            "-i",
            str(inventory_path.resolve()),
            str(abs_playbook_path),
        ]
        if tags:
            cmd.extend(["--tags", ",".join(tags)])
        if limit_hosts:
            cmd.extend(["--limit", ",".join(limit_hosts)])

        # Write extravars to a transient JSON file.
        env_dir = self.private_data_dir / "env"
        env_dir.mkdir(parents=True, exist_ok=True)
        extravars_file = env_dir / "extravars.json"
        extravars_file.write_text(json.dumps(extravars))
        cmd.extend(["-e", f"@{extravars_file.resolve()}"])

        env = os.environ.copy()
        env.update(envvars)

        logger.debug("Executing Ansible command: %s", " ".join(cmd))
        logger.debug("Ansible Env: %s", envvars)

        if self.stream_output:
            proc = subprocess.Popen(
                cmd,
                cwd=self.private_data_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                if self.output_callback:
                    self.output_callback(line.rstrip("\n"), "\n")
                else:
                    sys.stdout.write(line)
            proc.wait()
            rc = proc.returncode
        else:
            completed = subprocess.run(
                cmd,
                cwd=self.private_data_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            rc = completed.returncode
            if rc != 0:
                logger.error("ansible-playbook failed rc=%s", rc)
                logger.error("stdout: %s", completed.stdout)
                logger.error("stderr: %s", completed.stderr)

        status = "successful" if rc == 0 else "failed"
        return ExecutionResult(rc=rc, status=status, stats={})


def _render_inventory(hosts: List[Any]) -> str:
    """Render an INI inventory from host configs."""
    lines = ["[all]"]
    for host in hosts:
        lines.append(host.ansible_host_line())
    lines.append("")
    lines.append("[cluster]")
    for host in hosts:
        lines.append(host.ansible_host_line())
    return "\n".join(lines) + "\n"
