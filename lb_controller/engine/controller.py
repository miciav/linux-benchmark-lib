"""Controller module coordinating remote benchmark execution via Ansible.

This module keeps orchestration logic inside Python while delegating remote
execution to Ansible Runner.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from lb_plugins.api import PluginAssetConfig
from lb_runner.api import BenchmarkConfig, RemoteHostConfig, RunEvent, StopToken

from lb_controller.models.state import ControllerState, ControllerStateMachine
from lb_controller.adapters.ansible_runner import AnsibleRunnerExecutor
from lb_controller.services.journal import RunJournal
from lb_controller.adapters.playbooks import (
    execute_run_playbook,
    handle_collect_phase,
    run_for_hosts,
    run_global_setup,
    run_global_teardown,
    run_teardown_playbook,
    run_workload_execution,
    run_workload_setup,
)
from lb_controller.engine.stop_logic import handle_stop_during_workloads, handle_stop_protocol
from lb_controller.services.paths import generate_run_id, prepare_per_host_dirs, prepare_run_dirs
from lb_controller.engine.stops import StopCoordinator
from lb_controller.engine.lifecycle import RunLifecycle, RunPhase
from lb_controller.models.types import (
    ExecutionResult,
    InventorySpec,
    RemoteExecutor,
    RunExecutionSummary,
)
from lb_controller.models.pending import pending_hosts_for, pending_repetitions

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
        from lb_controller.services.paths import apply_playbook_defaults
        from lb_plugins.api import apply_plugin_assets, create_registry
        apply_playbook_defaults(self.config)
        if not self.config.plugin_assets:
            apply_plugin_assets(self.config, create_registry())
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
            "lb_upgrade_pip": self.config.remote_execution.upgrade_pip,
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
        return run_global_setup(self, state, phases, flags, ui_log)

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

        pending_hosts = pending_hosts_for(
            state.active_journal, state.target_reps, test_name, self.config.remote_hosts
        )
        if not pending_hosts:
            ui_log(f"All repetitions already completed for {test_name}, skipping.")
            return True

        plugin_assets = self._get_plugin_assets(workload_cfg.plugin, test_name, ui_log, flags)

        if self.stop_token and self.stop_token.should_stop():
            self._handle_stop_during_workloads(
                state.inventory, state.extravars, flags, ui_log
            )
            return False

        pending_reps = pending_repetitions(
            state.active_journal, state.target_reps, pending_hosts, test_name
        )

        self._run_workload_setup(
            test_name,
            plugin_assets,
            workload_cfg.plugin,
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
            plugin_assets,
            workload_cfg.plugin,
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
        return handle_stop_during_workloads(self, inventory, extravars, flags, ui_log)

    def _get_plugin_assets(
        self,
        plugin_name: str,
        test_name: str,
        ui_log: Callable[[str], None],
        flags: _RunFlags,
    ) -> PluginAssetConfig | None:
        assets = self.config.plugin_assets.get(plugin_name)
        if assets is None:
            ui_log(
                f"No plugin assets found for {test_name} ({plugin_name}); skipping setup/teardown."
            )
        return assets

    def _run_workload_setup(
        self,
        test_name: str,
        plugin_assets: PluginAssetConfig | None,
        plugin_name: str,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
        pending_reps: Dict[str, List[int]],
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        run_workload_setup(
            self,
            test_name,
            plugin_assets,
            plugin_name,
            inventory,
            extravars,
            pending_reps,
            phases,
            flags,
            ui_log,
        )

    def _run_workload_execution(
        self,
        test_name: str,
        plugin_assets: PluginAssetConfig | None,
        plugin_name: str,
        state: _RunState,
        pending_hosts: List[RemoteHostConfig],
        pending_reps: Dict[str, List[int]],
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        run_workload_execution(
            self,
            test_name,
            plugin_assets,
            plugin_name,
            state,
            pending_hosts,
            pending_reps,
            phases,
            flags,
            ui_log,
        )

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
        execute_run_playbook(
            self,
            test_name,
            pending_hosts,
            pending_reps,
            state,
            phases,
            flags,
            ui_log,
        )

    def _handle_collect_phase(
        self,
        test_name: str,
        pending_hosts: List[RemoteHostConfig],
        state: _RunState,
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        handle_collect_phase(
            self,
            test_name,
            pending_hosts,
            state,
            phases,
            flags,
            ui_log,
        )

    def _run_global_teardown(
        self,
        state: _RunState,
        phases: Dict[str, ExecutionResult],
        flags: _RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        run_global_teardown(self, state, phases, flags, ui_log)

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
        return handle_stop_protocol(self, inventory, extravars, log_fn)

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
        return run_for_hosts(self, playbook_path, base_inventory, hosts, extravars, tags)
