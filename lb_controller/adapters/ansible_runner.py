"""Ansible-based remote executor implementation."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lb_controller.adapters.ansible_helpers import (
    AnsibleEnvBuilder,
    ExtravarsWriter,
    InventoryWriter,
    PlaybookCommandBuilder,
    PlaybookProcessRunner,
)
from lb_controller.models.types import ExecutionResult, InventorySpec, RemoteExecutor
from lb_runner.api import StopToken

logger = logging.getLogger(__name__)
ANSIBLE_ROOT = Path(__file__).resolve().parent.parent / "ansible"


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
        self._active_label: str | None = None
        # Force Ansible temp into a writable location inside the runner dir to avoid
        # host-level permission issues.
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
        self._inventory_writer = InventoryWriter(self.private_data_dir)
        self._env_builder = AnsibleEnvBuilder(
            private_data_dir=self.private_data_dir,
            local_tmp=self.local_tmp,
            event_log_path=self.event_log_path,
            ansible_root=ANSIBLE_ROOT,
        )
        self._extravars_writer = ExtravarsWriter(self.private_data_dir)
        self._command_builder = PlaybookCommandBuilder()
        self._process_runner = PlaybookProcessRunner(
            private_data_dir=self.private_data_dir,
            stream_output=self.stream_output,
            output_callback=self.output_callback,
            stop_token=self.stop_token,
        )

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
        self._process_runner.clear_interrupt()
        stop_result = self._maybe_stop(cancellable)
        if stop_result is not None:
            return stop_result
        if not playbook_path.exists():
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")

        inventory_path = self._inventory_writer.prepare(inventory)
        runner_fn = self._runner_fn or self._import_runner()

        # Ensure playbook path is absolute so runner can find it
        # regardless of private_data_dir location
        abs_playbook_path = playbook_path.resolve()

        label = abs_playbook_path.name
        logger.info(
            "Running playbook %s against %d host(s)", label, len(inventory.hosts)
        )
        self._active_label = label

        merged_extravars = self._merge_extravars(extravars, inventory_path)
        envvars = self._env_builder.build()

        try:
            result = self._execute_playbook(
                runner_fn=runner_fn,
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

        return self._finalize_result(playbook_path, result)

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
        Execute ansible-playbook via subprocess to avoid ansible-runner's
        awx_display callback.
        """
        cmd = self._command_builder.build(
            abs_playbook_path, inventory_path, tags, limit_hosts
        )
        extravars_file = self._extravars_writer.write(extravars)
        cmd.extend(["-e", f"@{extravars_file.resolve()}"])

        env = self._env_builder.merge_env(envvars)
        self._log_subprocess_command(cmd, envvars)

        return self._process_runner.run(cmd, env, cancellable=cancellable)

    @staticmethod
    def _log_subprocess_command(cmd: list[str], envvars: Dict[str, str]) -> None:
        logger.debug("Executing Ansible command: %s", " ".join(cmd))
        logger.debug("Ansible Env: %s", envvars)

    def interrupt(self) -> None:
        """Request interruption of the current playbook execution."""
        self._process_runner.interrupt()
        self._active_label = None

    @property
    def is_running(self) -> bool:
        """Return True when a playbook is in-flight."""
        if self._process_runner.is_running():
            return True
        return self._active_label is not None

    @property
    def _active_process(self):  # type: ignore[override]
        return self._process_runner.get_active_process()

    @_active_process.setter
    def _active_process(self, proc):  # type: ignore[override]
        self._process_runner.set_active_process(proc)

    def _maybe_stop(self, cancellable: bool) -> ExecutionResult | None:
        if not self._process_runner.should_stop(cancellable):
            return None
        return ExecutionResult(rc=1, status="stopped", stats={})

    @staticmethod
    def _merge_extravars(
        extravars: Optional[Dict[str, Any]],
        inventory_path: Path,
    ) -> Dict[str, Any]:
        merged = extravars.copy() if extravars else {}
        merged.setdefault("_lb_inventory_path", str(inventory_path))
        return merged

    def _execute_playbook(
        self,
        *,
        runner_fn: Callable[..., Any],
        abs_playbook_path: Path,
        inventory_path: Path,
        extravars: Dict[str, Any],
        tags: Optional[List[str]],
        envvars: Dict[str, str],
        limit_hosts: Optional[List[str]],
        cancellable: bool,
    ) -> Any:
        if self._runner_fn:
            return runner_fn(
                private_data_dir=str(self.private_data_dir),
                playbook=str(abs_playbook_path),
                inventory=str(inventory_path.resolve()),
                extravars=extravars,
                tags=",".join(tags) if tags else None,
                envvars=envvars,
                limit=",".join(limit_hosts) if limit_hosts else None,
            )
        return self._run_subprocess_playbook(
            abs_playbook_path=abs_playbook_path,
            inventory_path=inventory_path,
            extravars=extravars,
            tags=tags,
            envvars=envvars,
            limit_hosts=limit_hosts,
            cancellable=cancellable,
        )

    @staticmethod
    def _finalize_result(
        playbook_path: Path, result: Any
    ) -> ExecutionResult:
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
