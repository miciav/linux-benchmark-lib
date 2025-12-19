"""Controller module coordinating remote benchmark execution via Ansible.

This module keeps orchestration logic inside Python while delegating remote
execution to Ansible Runner.
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from lb_runner.benchmark_config import BenchmarkConfig, RemoteHostConfig
from lb_runner.stop_token import StopToken

from lb_controller.controller_state import ControllerState, ControllerStateMachine
from lb_controller.ansible_executor import AnsibleRunnerExecutor
from lb_controller.journal import RunJournal, RunStatus
from lb_controller.journal_sync import (
    backfill_timings_from_results,
    update_all_reps,
)
from lb_controller.paths import generate_run_id, prepare_per_host_dirs, prepare_run_dirs
from lb_controller.services.plugin_service import create_registry
from lb_controller.stop_coordinator import StopCoordinator, StopState
from lb_controller.lifecycle import RunLifecycle, RunPhase, StopStage
from lb_controller.types import (
    ExecutionResult,
    InventorySpec,
    RemoteExecutor,
    RunExecutionSummary,
)
from lb_runner.events import RunEvent

logger = logging.getLogger(__name__)


@dataclass
class _RunState:
    """Internal container for a controller run."""

    resolved_run_id: str
    inventory: InventorySpec
    target_reps: int
    output_root: Path
    report_root: Path
    data_export_root: Path
    per_host_output: Dict[str, Path]
    active_journal: RunJournal
    journal_file: Path
    extravars: Dict[str, Any]
    test_types: List[str]


@dataclass
class _RunFlags:
    """Mutable flags tracking stop/progress outcomes."""

    all_tests_success: bool = True
    stop_successful: bool = True
    stop_protocol_attempted: bool = False


class BenchmarkController:
    """Controller coordinating remote benchmark runs."""

    def __init__(
        self,
        config: BenchmarkConfig,
        executor: Optional[RemoteExecutor] = None,
        output_callback: Optional[Callable[[str, str], None]] = None,
        output_formatter: Optional[Any] = None,  # Inject the formatter instance
        journal_refresh: Optional[Callable[[], None]] = None,
        stop_token: StopToken | None = None,
        stop_timeout_s: float = 30.0,
        state_machine: ControllerStateMachine | None = None,
    ):
        self.config = config
        self.output_formatter = output_formatter
        self.stop_token = stop_token
        self._stop_timeout_s = stop_timeout_s
        self.lifecycle = RunLifecycle()
        self.state_machine = state_machine or ControllerStateMachine()
        # Enable streaming if a callback is provided
        stream = output_callback is not None
        self.executor = executor or AnsibleRunnerExecutor(
            output_callback=output_callback,
            stream_output=stream,
            stop_token=stop_token,
        )
        self.plugin_registry = create_registry()
        self._journal_refresh = journal_refresh
        # Use event stream as the source of truth; avoid mass RUNNING/COMPLETED updates.
        self._use_progress_stream = True
        self.coordinator: Optional[StopCoordinator] = None

    def on_event(self, event: RunEvent) -> None:
        """Process an event for stop coordination."""
        if self.coordinator:
            self.coordinator.process_event(event)

    def _transition(self, state: ControllerState, reason: str | None = None) -> None:
        """Transition controller state and ignore invalid jumps silently."""
        try:
            self.state_machine.transition(state, reason=reason)
        except ValueError:
            logger.debug("Invalid transition ignored: %s -> %s", self.state_machine.state, state)

    def _arm_stop(self, reason: str | None = None) -> None:
        """Arm a coordinated stop (idempotent)."""
        try:
            self.state_machine.transition(ControllerState.STOP_ARMED, reason=reason)
        except Exception:
            pass

    def _stop_requested(self) -> bool:
        """Return True when a stop was requested and arm the stop state."""
        if self.stop_token and self.stop_token.should_stop():
            self._arm_stop("stop requested")
            return True
        return False

    def _refresh_journal(self) -> None:
        """Trigger UI journal refresh callback when available."""
        if not self._journal_refresh:
            return
        try:
            self._journal_refresh()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Journal refresh callback failed: %s", exc)

    def run(
        self,
        test_types: List[str],
        run_id: Optional[str] = None,
        journal: Optional[RunJournal] = None,
        resume: bool = False,
        journal_path: Optional[Path] = None,
    ) -> RunExecutionSummary:
        """
        Execute the configured benchmarks on remote hosts.

        Args:
            test_types: List of benchmark identifiers to execute.
            run_id: Optional run identifier. If not provided, a timestamp-based
                id is generated.
            journal: Optional pre-loaded journal used for resume flows.
            resume: When True, reuse the provided journal instead of creating a new one.
            journal_path: Optional override for where the journal is persisted.
        """
        if not self.config.remote_hosts:
            raise ValueError("At least one remote host must be configured.")
        if resume and journal is None:
            raise ValueError("Resume requested without a journal instance.")

        phases: Dict[str, ExecutionResult] = {}
        flags = _RunFlags()
        state = self._prepare_run_state(test_types, run_id, journal, journal_path)

        def ui_log(msg: str) -> None:
            logger.info(msg)

        ui_log(f"Starting Run {state.resolved_run_id}")

        if self.config.remote_execution.run_setup:
            early_summary = self._run_global_setup(state, phases, flags, ui_log)
            if early_summary:
                return early_summary

        if (
            not self._stop_requested()
            and self.state_machine.state != ControllerState.RUNNING_WORKLOADS
        ):
            self._transition(ControllerState.RUNNING_WORKLOADS)

        flags = self._run_workloads(state, phases, flags, ui_log)
        self._run_global_teardown(state, phases, flags, ui_log)

        ui_log("Run Finished.")
        time.sleep(1)

        self.lifecycle.finish()
        return self._build_summary(state, phases, flags)

    def _prepare_run_state(
        self,
        test_types: List[str],
        run_id: Optional[str],
        journal: Optional[RunJournal],
        journal_path: Optional[Path],
    ) -> _RunState:
        resolved_run_id = (
            journal.run_id if journal is not None else run_id or generate_run_id()
        )
        inventory = InventorySpec(
            hosts=self.config.remote_hosts,
            inventory_path=self.config.remote_execution.inventory_path,
        )

        self.coordinator = StopCoordinator(
            expected_runners={h.name for h in self.config.remote_hosts},
            stop_timeout=self._stop_timeout_s,
            run_id=resolved_run_id,
        )
        initial_state = (
            ControllerState.RUNNING_GLOBAL_SETUP
            if self.config.remote_execution.run_setup
            else ControllerState.RUNNING_WORKLOADS
        )
        self._transition(initial_state)
        self.lifecycle.start_phase(
            RunPhase.GLOBAL_SETUP
            if self.config.remote_execution.run_setup
            else RunPhase.WORKLOADS
        )

        target_reps = (
            journal.metadata.get("repetitions") if journal else None
        ) or self.config.repetitions

        output_root, report_root, data_export_root = prepare_run_dirs(
            self.config, resolved_run_id
        )
        per_host_output = prepare_per_host_dirs(
            self.config.remote_hosts, output_root=output_root, report_root=report_root
        )

        active_journal = journal or RunJournal.initialize(
            resolved_run_id, self.config, test_types
        )
        journal_file = journal_path or output_root / "run_journal.json"
        active_journal.save(journal_file)
        if self._journal_refresh:
            self._journal_refresh()

        remote_output_root = f"/tmp/benchmark_results/{resolved_run_id}"
        extravars = {
            "run_id": resolved_run_id,
            "output_root": str(output_root),
            "remote_output_root": remote_output_root,
            "report_root": str(report_root),
            "data_export_root": str(data_export_root),
            "lb_workdir": "/opt/lb",
            "per_host_output": {k: str(v) for k, v in per_host_output.items()},
            "benchmark_config": self.config.model_dump(mode="json"),
            "use_container_fallback": self.config.remote_execution.use_container_fallback,
            "collector_apt_packages": sorted(self._collector_apt_packages()),
            "workload_runner_install_deps": False,
            "repetitions_total": target_reps,
            "repetition_index": 0,
        }

        return _RunState(
            resolved_run_id=resolved_run_id,
            inventory=inventory,
            target_reps=target_reps,
            output_root=output_root,
            report_root=report_root,
            data_export_root=data_export_root,
            per_host_output=per_host_output,
            active_journal=active_journal,
            journal_file=journal_file,
            extravars=extravars,
            test_types=list(test_types),
        )

    def _run_global_setup(
        self,
        state: _RunState,
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> RunExecutionSummary | None:
        if self._stop_requested():
            ui_log("Stop requested before setup; arming stop and skipping workloads.")
            self.lifecycle.arm_stop()
            self.lifecycle.mark_interrupting_setup()
            self._transition(
                ControllerState.STOPPING_INTERRUPT_SETUP,
                reason="stop before setup",
            )
            state.test_types = []
            return None

        ui_log("Phase: Global Setup")
        if self.output_formatter:
            self.output_formatter.set_phase("Global Setup")
        phases["setup_global"] = self.executor.run_playbook(
            self.config.remote_execution.setup_playbook,
            inventory=state.inventory,
            extravars=state.extravars,
        )
        if self._stop_requested():
            self.lifecycle.arm_stop()
            self.lifecycle.mark_interrupting_setup()
            self._transition(
                ControllerState.STOPPING_INTERRUPT_SETUP,
                reason="stop during setup",
            )
            self._interrupt_executor()
            flags.all_tests_success = False
            try:
                phases["setup_global"].status = "stopped"
            except Exception:
                pass
            state.test_types = []
            return None

        if not phases["setup_global"].success:
            ui_log("Global setup failed. Aborting run.")
            self._transition(ControllerState.FAILED, reason="global setup failed")
            self._refresh_journal()
            return self._build_summary(state, phases, flags, success_override=False)
        return None

    def _run_workloads(
        self,
        state: _RunState,
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> _RunFlags:
        self.lifecycle.start_phase(RunPhase.WORKLOADS)
        for test_name in state.test_types:
            if self._stop_requested():
                flags = self._handle_stop_during_workloads(
                    state.inventory, state.extravars, flags, ui_log
                )
                break
            if not self._process_single_workload(test_name, state, phases, flags, ui_log):
                break

        return flags

    def _process_single_workload(
        self,
        test_name: str,
        state: _RunState,
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> bool:
        workload_cfg = self.config.workloads.get(test_name)
        if not workload_cfg:
            ui_log(f"Skipping unknown workload: {test_name}")
            return True

        pending_hosts = self._pending_hosts_for(
            state.active_journal, state.target_reps, test_name
        )
        if not pending_hosts:
            ui_log(f"All repetitions already completed for {test_name}, skipping.")
            return True

        plugin = self._get_plugin_or_skip(workload_cfg.plugin, test_name, ui_log, flags)
        if plugin is None:
            return True

        if self.stop_token and self.stop_token.should_stop():
            self._handle_stop_during_workloads(
                state.inventory, state.extravars, flags, ui_log
            )
            return False

        pending_reps = self._pending_repetitions(
            state.active_journal, state.target_reps, pending_hosts, test_name
        )

        self._run_workload_setup(
            test_name,
            plugin,
            state.inventory,
            state.extravars,
            pending_reps,
            phases,
            flags,
            ui_log,
        )
        if not pending_reps:
            return True
        if self._stop_requested():
            self._handle_stop_during_workloads(
                state.inventory, state.extravars, flags, ui_log
            )
            return False

        self._run_workload_execution(
            test_name,
            plugin,
            state,
            pending_hosts,
            pending_reps,
            phases,
            flags,
            ui_log,
        )

        if self._stop_requested():
            self._handle_stop_during_workloads(
                state.inventory, state.extravars, flags, ui_log
            )
            return False
        return True

    def _handle_stop_during_workloads(
        self,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> _RunFlags:
        self.lifecycle.arm_stop()
        self.lifecycle.mark_waiting_runners()
        self._transition(
            ControllerState.STOPPING_WAIT_RUNNERS,
            reason="stop during workloads",
        )
        flags.stop_protocol_attempted = True
        flags.stop_successful = self._handle_stop_protocol(inventory, extravars, ui_log)
        flags.all_tests_success = False
        return flags

    def _get_plugin_or_skip(
        self,
        plugin_name: str,
        test_name: str,
        ui_log: Callable[[str], None],
        flags: _RunFlags,
    ):
        try:
            return self.plugin_registry.get(plugin_name)
        except Exception as exc:
            ui_log(f"Failed to load plugin for {test_name}: {exc}")
            flags.all_tests_success = False
            return None

    def _pending_hosts_for(
        self, journal: RunJournal, target_reps: int, test_name: str
    ) -> List[RemoteHostConfig]:
        hosts: List[RemoteHostConfig] = []
        for host in self.config.remote_hosts:
            for rep in range(1, target_reps + 1):
                if journal.should_run(host.name, test_name, rep):
                    hosts.append(host)
                    break
        return hosts

    def _pending_repetitions(
        self,
        journal: RunJournal,
        target_reps: int,
        hosts: List[RemoteHostConfig],
        test_name: str,
    ) -> Dict[str, List[int]]:
        pending_reps: Dict[str, List[int]] = {}
        for host in hosts:
            reps_for_host: List[int] = []
            for rep in range(1, target_reps + 1):
                if journal.should_run(host.name, test_name, rep):
                    reps_for_host.append(rep)
            pending_reps[host.name] = reps_for_host or [1]
        return pending_reps

    def _run_workload_setup(
        self,
        test_name: str,
        plugin: Any,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
        pending_reps: Dict[str, List[int]],
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        setup_pb = plugin.get_ansible_setup_path()
        if not setup_pb:
            return
        ui_log(f"Setup: {test_name} ({plugin.name})")
        if self.output_formatter:
            self.output_formatter.set_phase(f"Setup: {test_name}")
        setup_extravars = extravars.copy()
        try:
            setup_extravars.update(plugin.get_ansible_setup_extravars())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Failed to compute setup extravars for %s: %s", plugin.name, exc)
        res = self.executor.run_playbook(
            setup_pb,
            inventory=inventory,
            extravars=setup_extravars,
        )
        phases[f"setup_{test_name}"] = res
        if not res.success:
            ui_log(f"Setup failed for {test_name}")
            flags.all_tests_success = False
            self._run_teardown_playbook(plugin, inventory, extravars)
            # Mark pending reps to avoid running workload
            pending_reps.clear()

    def _run_workload_execution(
        self,
        test_name: str,
        plugin: Any,
        state: _RunState,
        pending_hosts: List[RemoteHostConfig],
        pending_reps: Dict[str, List[int]],
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        if not pending_reps:
            return
        self._execute_run_playbook(
            test_name,
            pending_hosts,
            pending_reps,
            state,
            phases,
            flags,
            ui_log,
        )
        if self.stop_token and self.stop_token.should_stop():
            flags = self._handle_stop_during_workloads(
                state.inventory, state.extravars, flags, ui_log
            )
            return
        self._handle_collect_phase(
            test_name, pending_hosts, state, phases, flags, ui_log
        )
        self._run_teardown_playbook(plugin, state.inventory, state.extravars)

    def _execute_run_playbook(
        self,
        test_name: str,
        pending_hosts: List[RemoteHostConfig],
        pending_reps: Dict[str, List[int]],
        state: _RunState,
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        ui_log(f"Run: {test_name} on {len(pending_hosts)} host(s)")
        if self.output_formatter:
            self.output_formatter.set_phase(f"Run: {test_name}")
        if not self._use_progress_stream:
            update_all_reps(
                self.config.repetitions,
                state.active_journal,
                state.journal_file,
                pending_hosts,
                test_name,
                RunStatus.RUNNING,
                action="Running workload...",
                refresh=self._journal_refresh,
            )

        loop_extravars = state.extravars.copy()
        loop_extravars["tests"] = [test_name]
        loop_extravars["pending_repetitions"] = pending_reps

        res_run = self.executor.run_playbook(
            self.config.remote_execution.run_playbook,
            inventory=state.inventory,
            extravars=loop_extravars,
        )
        phases[f"run_{test_name}"] = res_run
        status = RunStatus.COMPLETED if res_run.success else RunStatus.FAILED

        if not self._use_progress_stream:
            update_all_reps(
                self.config.repetitions,
                state.active_journal,
                state.journal_file,
                pending_hosts,
                test_name,
                status,
                action="Completed" if res_run.success else "Failed",
                error=None if res_run.success else "ansible-playbook failed",
                refresh=self._journal_refresh,
            )

        if not res_run.success:
            ui_log(f"Run failed for {test_name}")
            flags.all_tests_success = False

    def _handle_collect_phase(
        self,
        test_name: str,
        pending_hosts: List[RemoteHostConfig],
        state: _RunState,
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        res_run = phases.get(f"run_{test_name}")
        status = RunStatus.COMPLETED if res_run and res_run.success else RunStatus.FAILED
        if self.config.remote_execution.run_collect:
            ui_log(f"Collect: {test_name}")
            if self.output_formatter:
                self.output_formatter.set_phase(f"Collect: {test_name}")
            if not self._use_progress_stream:
                update_all_reps(
                    self.config.repetitions,
                    state.active_journal,
                    state.journal_file,
                    pending_hosts,
                    test_name,
                    status,
                    action="Collecting results",
                    refresh=self._journal_refresh,
                )
            res_col = self.executor.run_playbook(
                self.config.remote_execution.collect_playbook,
                inventory=state.inventory,
                extravars=state.extravars,
            )
            phases[f"collect_{test_name}"] = res_col
            backfill_timings_from_results(
                state.active_journal,
                state.journal_file,
                pending_hosts,
                test_name,
                state.per_host_output,
                refresh=self._journal_refresh,
            )
        else:
            backfill_timings_from_results(
                state.active_journal,
                state.journal_file,
                pending_hosts,
                test_name,
                state.per_host_output,
                refresh=self._journal_refresh,
            )
            phases[f"collect_{test_name}"] = ExecutionResult(
                rc=0, status="skipped", stats={}
            )
            if not self._use_progress_stream:
                update_all_reps(
                    self.config.repetitions,
                    state.active_journal,
                    state.journal_file,
                    pending_hosts,
                    test_name,
                    status,
                    action="Done",
                    refresh=self._journal_refresh,
                )

    def _run_teardown_playbook(
        self,
        plugin: Any,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
    ) -> None:
        teardown_pb = plugin.get_ansible_teardown_path()
        if not teardown_pb:
            return
        td_extravars = extravars.copy()
        try:
            td_extravars.update(plugin.get_ansible_teardown_extravars())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "Failed to compute teardown extravars for %s: %s",
                plugin.name,
                exc,
            )
        self.executor.run_playbook(
            teardown_pb,
            inventory=inventory,
            extravars=td_extravars,
            cancellable=False,
        )

    def _run_global_teardown(
        self,
        state: _RunState,
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        if not self.config.remote_execution.run_teardown:
            return
        stopping_now = self._stop_requested()
        if stopping_now and self.state_machine.state not in {
            ControllerState.STOPPING_TEARDOWN,
            ControllerState.STOPPING_INTERRUPT_TEARDOWN,
        }:
            self._transition(
                ControllerState.STOPPING_TEARDOWN, reason="teardown after stop"
            )
        elif not stopping_now and self.state_machine.state not in {
            ControllerState.STOPPING_TEARDOWN,
            ControllerState.STOPPING_INTERRUPT_TEARDOWN,
        }:
            self._transition(ControllerState.RUNNING_GLOBAL_TEARDOWN)
        self.lifecycle.start_phase(RunPhase.GLOBAL_TEARDOWN)
        if flags.stop_protocol_attempted and not flags.stop_successful:
            ui_log("Stop protocol failed/timed out; proceeding with best-effort teardown.")
            phases["stop_protocol"] = ExecutionResult(rc=1, status="failed", stats={})

        ui_log("Phase: Global Teardown")
        if self.output_formatter:
            self.output_formatter.set_phase("Global Teardown")

        if not self.config.remote_execution.teardown_playbook:
            ui_log("No teardown playbook configured.")
            return

        if self._stop_requested():
            self.lifecycle.arm_stop()
            self.lifecycle.mark_interrupting_teardown()
            self._transition(
                ControllerState.STOPPING_INTERRUPT_TEARDOWN,
                reason="stop during teardown",
            )
            self._interrupt_executor()
        phases["teardown_global"] = self.executor.run_playbook(
            self.config.remote_execution.teardown_playbook,
            inventory=state.inventory,
            extravars=state.extravars,
            cancellable=False,
        )
        if not phases["teardown_global"].success:
            ui_log("Global teardown failed to clean up perfectly.")

    def _build_summary(
        self,
        state: _RunState,
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        success_override: Optional[bool] = None,
    ) -> RunExecutionSummary:
        if self._stop_requested():
            final_state = (
                ControllerState.STOP_FAILED
                if not flags.stop_successful
                else ControllerState.ABORTED
            )
        elif not flags.all_tests_success or success_override is False:
            final_state = ControllerState.FAILED
        else:
            final_state = ControllerState.FINISHED
        self._transition(final_state)
        success = (
            success_override
            if success_override is not None
            else flags.all_tests_success and flags.stop_successful
        )
        return RunExecutionSummary(
            run_id=state.resolved_run_id,
            per_host_output=state.per_host_output,
            phases=phases,
            success=bool(success),
            output_root=state.output_root,
            report_root=state.report_root,
            data_export_root=state.data_export_root,
            controller_state=self.state_machine.state,
            cleanup_allowed=self.state_machine.allows_cleanup(),
        )

    def _handle_stop_protocol(
        self,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
        log_fn: Callable[[str], None],
    ) -> bool:
        """
        Execute the distributed stop protocol.

        Returns:
            True if stop was confirmed by all runners (safe to teardown).
            False if stop timed out or failed (unsafe to teardown).
        """
        if not self.coordinator:
            return False  # Should not happen

        log_fn("Stop confirmed; initiating distributed stop protocol...")
        self._transition(ControllerState.STOPPING_WAIT_RUNNERS)
        self.coordinator.initiate_stop()
        self.lifecycle.mark_waiting_runners()

        # Create the STOP file on remote hosts
        # We construct a temporary playbook
        stop_pb_content = f"""
- hosts: all
  gather_facts: false
  tasks:
    - name: Create STOP file
      ansible.builtin.file:
        path: "{{{{ lb_workdir | default('/opt/lb') }}}}/STOP"
        state: touch
        mode: '0644'
"""

        # Execute stop playbook (non-cancellable, short timeout)
        # We can reuse executor but need to avoid re-triggering stop logic
        # since we are already stopping.
        # But run_playbook checks stop_token at start.
        # However, we are the controller, we want to run THIS specific task.
        # StopToken is triggered, so run_playbook will return immediately!
        # Fix: We need to bypass StopToken check or temporarily disable it?
        # AnsibleRunnerExecutor checks stop_token.
        # We can pass `cancellable=False` to `run_playbook`!

        log_fn("Sending stop signal to remote runners...")
        with tempfile.TemporaryDirectory(prefix="lb-stop-protocol-") as tmp_dir:
            stop_pb_path = Path(tmp_dir) / "stop_workload.yml"
            stop_pb_path.write_text(stop_pb_content, encoding="utf-8")
            res = self.executor.run_playbook(
                stop_pb_path,
                inventory=inventory,
                extravars=extravars,
                cancellable=False,
            )

        if not res.success:
            log_fn("Failed to send stop signal (playbook failure).")
            # We still wait, maybe some runners stopped anyway?
            # But likely we can't reach them.

        log_fn("Waiting for runners to confirm stop...")

        # Loop waiting for confirmation
        # The event loop is driven by the fact that `on_event` is called from
        # the background event tailer thread. We just poll the coordinator state.
        while True:
            self.coordinator.check_timeout()
            if self.coordinator.state == StopState.TEARDOWN_READY:
                log_fn("All runners confirmed stop.")
                self.lifecycle.mark_stopped()
                self._transition(
                    ControllerState.STOPPING_TEARDOWN, reason="runners stopped"
                )
                return True
            if self.coordinator.state == StopState.STOP_FAILED:
                log_fn("Stop protocol timed out or failed.")
                self.lifecycle.mark_failed()
                self._transition(
                    ControllerState.STOP_FAILED, reason="stop confirmations timed out"
                )
                return False

            time.sleep(0.5)

    def _interrupt_executor(self) -> None:
        exec_obj = self.executor
        if hasattr(exec_obj, "interrupt"):
            try:
                exec_obj.interrupt()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _collector_apt_packages(self) -> Set[str]:
        """Return apt packages needed for enabled collectors."""
        packages: Set[str] = set()
        if self.config.collectors.cli_commands:
            # sar/mpstat/iostat/pidstat
            packages.update({"sysstat", "procps"})
        return packages

    def _run_for_hosts(
        self,
        playbook_path: Path,
        base_inventory: InventorySpec,
        hosts: List[RemoteHostConfig],
        extravars: Dict[str, Any],
        tags: Optional[List[str]] = None,
    ) -> ExecutionResult:
        """Execute a playbook limited to the provided host list."""
        limit_hosts = [host.name for host in hosts]
        target_inventory = InventorySpec(
            hosts=hosts,
            inventory_path=base_inventory.inventory_path,
        )
        return self.executor.run_playbook(
            playbook_path,
            inventory=target_inventory,
            extravars=extravars,
            tags=tags,
            limit_hosts=limit_hosts,
        )
