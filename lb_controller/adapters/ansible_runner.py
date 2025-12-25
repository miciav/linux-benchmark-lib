"""Ansible-based remote executor implementation."""

from __future__ import annotations

import json
import logging
import os
import selectors
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lb_controller.models.types import ExecutionResult, InventorySpec, RemoteExecutor
from lb_runner.engine.stop_token import StopToken

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
        stop_token: StopToken | None = None,
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
        self.stop_token = stop_token
        self._interrupt_flag = threading.Event()
        self._active_process: subprocess.Popen[str] | None = None
        self._active_label: str | None = None
        self._lock = threading.Lock()
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
        *,
        cancellable: bool = True,
    ) -> ExecutionResult:
        """Execute a playbook using ansible-runner."""
        self._interrupt_flag.clear()
        if cancellable and (
            self._interrupt_flag.is_set()
            or (self.stop_token and self.stop_token.should_stop())
        ):
            return ExecutionResult(rc=1, status="stopped", stats={})
        if not playbook_path.exists():
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")

        inventory_path = self._prepare_inventory(inventory)
        runner_fn = self._runner_fn or self._import_runner()

        # Ensure playbook path is absolute so runner can find it
        # regardless of private_data_dir location
        abs_playbook_path = playbook_path.resolve()

        label = abs_playbook_path.name
        logger.info(
            "Running playbook %s against %d host(s)", label, len(inventory.hosts)
        )
        self._active_label = label

        merged_extravars = extravars.copy() if extravars else {}
        merged_extravars.setdefault("_lb_inventory_path", str(inventory_path))

        repo_roles = (ANSIBLE_ROOT / "roles").resolve()
        runner_roles = (self.private_data_dir / "roles").resolve()
        callback_dir = (ANSIBLE_ROOT / "callback_plugins").resolve()
        repo_collections = (ANSIBLE_ROOT / "collections").resolve()
        runner_collections = (self.private_data_dir / "collections").resolve()
        if repo_collections.exists():
            shutil.copytree(
                repo_collections,
                runner_collections,
                dirs_exist_ok=True,
            )
        envvars = {
            "ANSIBLE_ROLES_PATH": f"{runner_roles}:{repo_roles}",
            "ANSIBLE_COLLECTIONS_PATHS": f"{runner_collections}:{repo_collections}",
            "ANSIBLE_LOCAL_TEMP": str(self.local_tmp),
            "ANSIBLE_REMOTE_TMP": "/tmp/.ansible",
            "ANSIBLE_CONFIG": str((ANSIBLE_ROOT / "ansible.cfg").resolve()),
            # Use default callback; debug tasks echo LB_EVENT markers.
            "ANSIBLE_STDOUT_CALLBACK": "default",
            "ANSIBLE_CALLBACK_PLUGINS": str(callback_dir),
            "ANSIBLE_CALLBACKS_ENABLED": "lb_events",
            "LB_EVENT_LOG_PATH": str(self.event_log_path),
        }

        try:
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
                    cancellable=cancellable,
                )
        finally:
            self._active_label = None

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
        *,
        cancellable: bool = True,
    ) -> ExecutionResult:
        """
        Execute ansible-playbook via subprocess to avoid ansible-runner's awx_display callback.
        """
        cmd = self._build_playbook_cmd(
            abs_playbook_path, inventory_path, tags, limit_hosts
        )
        extravars_file = self._write_extravars(extravars)
        cmd.extend(["-e", f"@{extravars_file.resolve()}"])

        env = self._build_env(envvars)
        self._log_subprocess_command(cmd, envvars)

        if self.stream_output:
            return self._run_streaming_subprocess(cmd, env, cancellable)
        return self._run_capture_subprocess(cmd, env)

    def _build_playbook_cmd(
        self,
        abs_playbook_path: Path,
        inventory_path: Path,
        tags: Optional[List[str]],
        limit_hosts: Optional[List[str]],
    ) -> list[str]:
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
        return cmd

    def _write_extravars(self, extravars: Dict[str, Any]) -> Path:
        env_dir = self.private_data_dir / "env"
        env_dir.mkdir(parents=True, exist_ok=True)
        extravars_file = env_dir / "extravars.json"
        extravars_file.write_text(json.dumps(extravars))
        return extravars_file

    @staticmethod
    def _build_env(envvars: Dict[str, str]) -> Dict[str, str]:
        env = os.environ.copy()
        env.update(envvars)
        return env

    @staticmethod
    def _log_subprocess_command(cmd: list[str], envvars: Dict[str, str]) -> None:
        logger.debug("Executing Ansible command: %s", " ".join(cmd))
        logger.debug("Ansible Env: %s", envvars)

    def _run_streaming_subprocess(
        self, cmd: list[str], env: Dict[str, str], cancellable: bool
    ) -> ExecutionResult:
        proc = subprocess.Popen(
            cmd,
            cwd=self.private_data_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        with self._lock:
            self._active_process = proc
        stop_requested = self._stream_process_output(proc, cancellable)
        rc = self._finalize_process(proc, stop_requested)
        if stop_requested or self._should_stop(cancellable):
            return ExecutionResult(rc=rc or 1, status="stopped", stats={})
        status = "successful" if rc == 0 else "failed"
        return ExecutionResult(rc=rc, status=status, stats={})

    def _run_capture_subprocess(
        self, cmd: list[str], env: Dict[str, str]
    ) -> ExecutionResult:
        completed = subprocess.run(
            cmd,
            cwd=self.private_data_dir,
            env=env,
            capture_output=True,
            text=True,
            start_new_session=True,
        )
        rc = completed.returncode
        if rc != 0:
            logger.error("ansible-playbook failed rc=%s", rc)
            logger.error("stdout: %s", completed.stdout)
            logger.error("stderr: %s", completed.stderr)
        status = "successful" if rc == 0 else "failed"
        return ExecutionResult(rc=rc, status=status, stats={})

    def _stream_process_output(
        self, proc: subprocess.Popen[str], cancellable: bool
    ) -> bool:
        assert proc.stdout is not None
        stop_requested = False
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        try:
            while True:
                if self._should_stop(cancellable):
                    stop_requested = True
                    self._terminate_process(proc)
                    break
                if proc.poll() is not None:
                    break
                events = selector.select(timeout=0.1)
                if not events:
                    continue
                for key, _mask in events:
                    line = key.fileobj.readline()
                    if not line:
                        break
                    self._emit_stream_line(line)
        finally:
            selector.close()
            with self._lock:
                self._active_process = None
        return stop_requested

    def _emit_stream_line(self, line: str) -> None:
        if self.output_callback:
            self.output_callback(line.rstrip("\n"), "\n")
        else:
            sys.stdout.write(line)
            sys.stdout.flush()

    def _finalize_process(
        self, proc: subprocess.Popen[str], stop_requested: bool
    ) -> int:
        try:
            proc.wait(timeout=5 if stop_requested else None)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return proc.returncode

    def _terminate_process(self, proc: subprocess.Popen[str]) -> None:
        try:
            proc.terminate()
        except Exception:
            pass

    def _should_stop(self, cancellable: bool) -> bool:
        return cancellable and (
            self._interrupt_flag.is_set()
            or (self.stop_token and self.stop_token.should_stop())
        )

    def interrupt(self) -> None:
        """Request interruption of the current playbook execution."""
        self._interrupt_flag.set()
        with self._lock:
            proc = self._active_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        with self._lock:
            self._active_process = None
            self._active_label = None

    @property
    def is_running(self) -> bool:
        """Return True when a playbook is in-flight."""
        with self._lock:
            if self._active_process and self._active_process.poll() is None:
                return True
        return self._active_label is not None


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
