"""Helper components for AnsibleRunnerExecutor."""

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

from lb_controller.models.types import ExecutionResult, InventorySpec
from lb_runner.api import StopToken

logger = logging.getLogger(__name__)


class InventoryWriter:
    """Write transient inventories into the runner workspace."""

    def __init__(self, private_data_dir: Path) -> None:
        self._private_data_dir = private_data_dir

    def prepare(self, inventory: InventorySpec) -> Path:
        if inventory.inventory_path:
            if not inventory.inventory_path.exists():
                raise FileNotFoundError(
                    f"Inventory file not found: {inventory.inventory_path}"
                )
            return inventory.inventory_path

        inventory_dir = self._private_data_dir / "inventory"
        inventory_dir.mkdir(parents=True, exist_ok=True)
        inventory_file = inventory_dir / "hosts.ini"
        inventory_file.write_text(render_inventory(inventory.hosts))
        return inventory_file


def render_inventory(hosts: List[Any]) -> str:
    """Render an INI inventory from host configs."""
    lines = ["[all]"]
    for host in hosts:
        lines.append(host.ansible_host_line())
    lines.append("")
    lines.append("[cluster]")
    for host in hosts:
        lines.append(host.ansible_host_line())
    return "\n".join(lines) + "\n"


class ExtravarsWriter:
    """Persist extravars payloads to disk for ansible-playbook."""

    def __init__(self, private_data_dir: Path) -> None:
        self._private_data_dir = private_data_dir

    def write(self, extravars: Dict[str, Any]) -> Path:
        env_dir = self._private_data_dir / "env"
        env_dir.mkdir(parents=True, exist_ok=True)
        extravars_file = env_dir / "extravars.json"
        extravars_file.write_text(json.dumps(extravars))
        return extravars_file


class PlaybookCommandBuilder:
    """Build ansible-playbook command arguments."""

    @staticmethod
    def build(
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


class AnsibleEnvBuilder:
    """Assemble environment variables for ansible-playbook."""

    def __init__(
        self,
        private_data_dir: Path,
        local_tmp: Path,
        event_log_path: Path,
        ansible_root: Path,
        event_debug: bool = False,
    ) -> None:
        self._private_data_dir = private_data_dir
        self._local_tmp = local_tmp
        self._event_log_path = event_log_path
        self._ansible_root = ansible_root
        self._event_debug = event_debug

    def build(self) -> Dict[str, str]:
        repo_roles = (self._ansible_root / "roles").resolve()
        runner_roles = (self._private_data_dir / "roles").resolve()
        callback_dir = (self._ansible_root / "callback_plugins").resolve()
        repo_collections = (self._ansible_root / "collections").resolve()
        runner_collections = (self._private_data_dir / "collections").resolve()
        if repo_collections.exists():
            shutil.copytree(
                repo_collections,
                runner_collections,
                dirs_exist_ok=True,
            )
        env = {
            "ANSIBLE_ROLES_PATH": f"{runner_roles}:{repo_roles}",
            "ANSIBLE_COLLECTIONS_PATHS": f"{runner_collections}:{repo_collections}",
            "ANSIBLE_LOCAL_TEMP": str(self._local_tmp),
            "ANSIBLE_REMOTE_TMP": "/tmp/.ansible",
            "ANSIBLE_CONFIG": str((self._ansible_root / "ansible.cfg").resolve()),
            "ANSIBLE_STDOUT_CALLBACK": "default",
            "ANSIBLE_CALLBACK_PLUGINS": str(callback_dir),
            "ANSIBLE_CALLBACKS_ENABLED": "lb_events",
            "LB_EVENT_LOG_PATH": str(self._event_log_path),
        }
        if self._event_debug:
            env["LB_EVENT_DEBUG"] = "1"
        return env

    @staticmethod
    def merge_env(envvars: Dict[str, str]) -> Dict[str, str]:
        env = os.environ.copy()
        env.update(envvars)
        return env


class ProcessStopController:
    """Track stop/interrupt state for a running subprocess."""

    def __init__(self, stop_token: StopToken | None) -> None:
        self._stop_token = stop_token
        self._interrupt_flag = threading.Event()
        self._active_process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def clear_interrupt(self) -> None:
        self._interrupt_flag.clear()

    def should_stop(self, cancellable: bool) -> bool:
        return cancellable and (
            self._interrupt_flag.is_set()
            or (self._stop_token and self._stop_token.should_stop())
        )

    def interrupt(self) -> None:
        self._interrupt_flag.set()
        self.terminate_active()

    def is_running(self) -> bool:
        with self._lock:
            if self._active_process and self._active_process.poll() is None:
                return True
        return False

    def set_active_process(self, proc: subprocess.Popen[str] | None) -> None:
        with self._lock:
            self._active_process = proc

    def get_active_process(self) -> subprocess.Popen[str] | None:
        with self._lock:
            return self._active_process

    def terminate_active(self) -> None:
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


class ProcessOutputStreamer:
    """Stream stdout from a subprocess to a callback or stdout."""

    def __init__(self, output_callback: Optional[Callable[[str, str], None]]) -> None:
        self._output_callback = output_callback

    def stream(
        self,
        proc: subprocess.Popen[str],
        *,
        should_stop: Callable[[], bool],
        terminate: Callable[[], None],
    ) -> bool:
        assert proc.stdout is not None
        stop_requested = False
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        try:
            while True:
                if self._should_terminate(should_stop, terminate):
                    stop_requested = True
                    break
                if proc.poll() is not None:
                    break
                if self._drain_ready_lines(selector):
                    break
        finally:
            selector.close()
        return stop_requested

    def emit_line(self, line: str) -> None:
        if self._output_callback:
            self._output_callback(line.rstrip("\n"), "\n")
        else:
            sys.stdout.write(line)
            sys.stdout.flush()

    def _should_terminate(
        self, should_stop: Callable[[], bool], terminate: Callable[[], None]
    ) -> bool:
        if not should_stop():
            return False
        terminate()
        return True

    def _drain_ready_lines(self, selector: selectors.BaseSelector) -> bool:
        events = selector.select(timeout=0.1)
        if not events:
            return False
        for key, _mask in events:
            line = key.fileobj.readline()
            if not line:
                return True
            self.emit_line(line)
        return False


class SubprocessRunner:
    """Run subprocesses with optional streaming and stop control."""

    def __init__(
        self,
        private_data_dir: Path,
        controller: ProcessStopController,
        streamer: ProcessOutputStreamer,
    ) -> None:
        self._private_data_dir = private_data_dir
        self._controller = controller
        self._streamer = streamer

    def run(
        self,
        cmd: list[str],
        env: Dict[str, str],
        *,
        stream_output: bool,
        cancellable: bool,
    ) -> ExecutionResult:
        if stream_output:
            return self._run_streaming(cmd, env, cancellable)
        return self._run_capture(cmd, env)

    def _run_streaming(
        self, cmd: list[str], env: Dict[str, str], cancellable: bool
    ) -> ExecutionResult:
        proc = subprocess.Popen(
            cmd,
            cwd=self._private_data_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self._controller.set_active_process(proc)
        try:
            stop_requested = self._streamer.stream(
                proc,
                should_stop=lambda: self._controller.should_stop(cancellable),
                terminate=self._controller.terminate_active,
            )
        finally:
            self._controller.set_active_process(None)
        rc = self._finalize_process(proc, stop_requested)
        if stop_requested or self._controller.should_stop(cancellable):
            return ExecutionResult(rc=rc or 1, status="stopped", stats={})
        status = "successful" if rc == 0 else "failed"
        return ExecutionResult(rc=rc, status=status, stats={})

    def _run_capture(self, cmd: list[str], env: Dict[str, str]) -> ExecutionResult:
        completed = subprocess.run(
            cmd,
            cwd=self._private_data_dir,
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

    @staticmethod
    def _finalize_process(proc: subprocess.Popen[str], stop_requested: bool) -> int:
        try:
            proc.wait(timeout=5 if stop_requested else None)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return proc.returncode


class PlaybookProcessRunner(ProcessStopController):
    """Handle subprocess-based ansible-playbook execution."""

    def __init__(
        self,
        private_data_dir: Path,
        stream_output: bool,
        output_callback: Optional[Callable[[str, str], None]],
        stop_token: StopToken | None,
    ) -> None:
        super().__init__(stop_token)
        self._private_data_dir = private_data_dir
        self._stream_output = stream_output
        self._runner = SubprocessRunner(
            private_data_dir=private_data_dir,
            controller=self,
            streamer=ProcessOutputStreamer(output_callback),
        )

    def run(
        self, cmd: list[str], env: Dict[str, str], *, cancellable: bool
    ) -> ExecutionResult:
        return self._runner.run(
            cmd,
            env,
            stream_output=self._stream_output,
            cancellable=cancellable,
        )
