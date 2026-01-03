"""Helper functions for controller playbook execution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from lb_controller.controller_state import ControllerState
from lb_controller.journal import RunStatus
from lb_controller.journal_sync import backfill_timings_from_results, update_all_reps
from lb_controller.lifecycle import RunPhase
from lb_controller.types import ExecutionResult, InventorySpec
from lb_runner.benchmark_config import RemoteHostConfig

if TYPE_CHECKING:
    from lb_controller.controller import BenchmarkController, _RunFlags, _RunState
    from lb_controller.types import RunExecutionSummary

logger = logging.getLogger(__name__)
setup_logger = logging.LoggerAdapter(logger, {"lb_phase": "setup"})
teardown_logger = logging.LoggerAdapter(logger, {"lb_phase": "teardown"})


def run_global_setup(
    controller: "BenchmarkController",
    state: "_RunState",
    phases: Dict[str, ExecutionResult],
    flags: "_RunFlags",
    ui_log: Callable[[str], None],
) -> "RunExecutionSummary | None":
    """Run the global setup playbook and return early summary when needed."""
    if controller._stop_requested():
        ui_log("Stop requested before setup; arming stop and skipping workloads.")
        controller.lifecycle.arm_stop()
        controller.lifecycle.mark_interrupting_setup()
        controller._transition(
            ControllerState.STOPPING_INTERRUPT_SETUP,
            reason="stop before setup",
        )
        state.test_types = []
        return None

    ui_log("Phase: Global Setup")
    if controller.output_formatter:
        controller.output_formatter.set_phase("Global Setup")
    setup_logger.info("Executing global setup playbook")
    phases["setup_global"] = controller.executor.run_playbook(
        controller.config.remote_execution.setup_playbook,
        inventory=state.inventory,
        extravars=state.extravars,
    )
    if controller._stop_requested():
        controller.lifecycle.arm_stop()
        controller.lifecycle.mark_interrupting_setup()
        controller._transition(
            ControllerState.STOPPING_INTERRUPT_SETUP,
            reason="stop during setup",
        )
        controller._interrupt_executor()
        flags.all_tests_success = False
        try:
            phases["setup_global"].status = "stopped"
        except Exception:
            pass
        state.test_types = []
        return None

    if not phases["setup_global"].success:
        ui_log("Global setup failed. Aborting run.")
        controller._transition(ControllerState.FAILED, reason="global setup failed")
        controller._refresh_journal()
        return controller._build_summary(state, phases, flags, success_override=False)
    return None


def run_workload_setup(
    controller: "BenchmarkController",
    test_name: str,
    plugin: Any,
    inventory: InventorySpec,
    extravars: Dict[str, Any],
    pending_reps: Dict[str, List[int]],
    phases: Dict[str, ExecutionResult],
    flags: "_RunFlags",
    ui_log: Callable[[str], None],
) -> None:
    """Execute per-workload setup playbook."""
    setup_pb = plugin.get_ansible_setup_path()
    if not setup_pb:
        return
    ui_log(f"Setup: {test_name} ({plugin.name})")
    if controller.output_formatter:
        controller.output_formatter.set_phase(f"Setup: {test_name}")
    setup_extravars = extravars.copy()
    try:
        setup_extravars.update(plugin.get_ansible_setup_extravars())
    except Exception as exc:  # pragma: no cover - defensive
        setup_logger.debug(
            "Failed to compute setup extravars for %s: %s", plugin.name, exc
        )
    setup_logger.info("Executing setup playbook for %s (%s)", test_name, plugin.name)
    res = controller.executor.run_playbook(
        setup_pb,
        inventory=inventory,
        extravars=setup_extravars,
    )
    phases[f"setup_{test_name}"] = res
    if not res.success:
        ui_log(f"Setup failed for {test_name}")
        flags.all_tests_success = False
        run_teardown_playbook(controller, plugin, inventory, extravars)
        pending_reps.clear()


def run_workload_execution(
    controller: "BenchmarkController",
    test_name: str,
    plugin: Any,
    state: "_RunState",
    pending_hosts: List[RemoteHostConfig],
    pending_reps: Dict[str, List[int]],
    phases: Dict[str, ExecutionResult],
    flags: "_RunFlags",
    ui_log: Callable[[str], None],
) -> None:
    """Execute run/collect/teardown for a workload."""
    if not pending_reps:
        return
    try:
        execute_run_playbook(
            controller,
            test_name,
            pending_hosts,
            pending_reps,
            state,
            phases,
            flags,
            ui_log,
        )
    finally:
        try:
            handle_collect_phase(
                controller, test_name, pending_hosts, state, phases, flags, ui_log
            )
        except Exception as exc:
            ui_log(f"Collect failed for {test_name}: {exc}")
    if controller.stop_token and controller.stop_token.should_stop():
        return
    run_teardown_playbook(controller, plugin, state.inventory, state.extravars)


def execute_run_playbook(
    controller: "BenchmarkController",
    test_name: str,
    pending_hosts: List[RemoteHostConfig],
    pending_reps: Dict[str, List[int]],
    state: "_RunState",
    phases: Dict[str, ExecutionResult],
    flags: "_RunFlags",
    ui_log: Callable[[str], None],
) -> None:
    """Run the workload execution playbook and update journal status."""
    ui_log(f"Run: {test_name} on {len(pending_hosts)} host(s)")
    if controller.output_formatter:
        controller.output_formatter.set_phase(f"Run: {test_name}")
    if not controller._use_progress_stream:
        update_all_reps(
            controller.config.repetitions,
            state.active_journal,
            state.journal_file,
            pending_hosts,
            test_name,
            RunStatus.RUNNING,
            action="Running workload...",
            refresh=controller._journal_refresh,
        )

    loop_extravars = state.extravars.copy()
    loop_extravars["tests"] = [test_name]
    loop_extravars["pending_repetitions"] = pending_reps

    res_run = controller.executor.run_playbook(
        controller.config.remote_execution.run_playbook,
        inventory=state.inventory,
        extravars=loop_extravars,
    )
    phases[f"run_{test_name}"] = res_run
    status = RunStatus.COMPLETED if res_run.success else RunStatus.FAILED

    if not controller._use_progress_stream:
        update_all_reps(
            controller.config.repetitions,
            state.active_journal,
            state.journal_file,
            pending_hosts,
            test_name,
            status,
            action="Completed" if res_run.success else "Failed",
            error=None if res_run.success else "ansible-playbook failed",
            refresh=controller._journal_refresh,
        )

    if not res_run.success:
        ui_log(f"Run failed for {test_name}")
        flags.all_tests_success = False


def handle_collect_phase(
    controller: "BenchmarkController",
    test_name: str,
    pending_hosts: List[RemoteHostConfig],
    state: "_RunState",
    phases: Dict[str, ExecutionResult],
    flags: "_RunFlags",
    ui_log: Callable[[str], None],
) -> None:
    """Execute the collect playbook and backfill timings."""
    res_run = phases.get(f"run_{test_name}")
    status = RunStatus.COMPLETED if res_run and res_run.success else RunStatus.FAILED
    if controller.config.remote_execution.run_collect:
        ui_log(f"Collect: {test_name}")
        if controller.output_formatter:
            controller.output_formatter.set_phase(f"Collect: {test_name}")
        if not controller._use_progress_stream:
            update_all_reps(
                controller.config.repetitions,
                state.active_journal,
                state.journal_file,
                pending_hosts,
                test_name,
                status,
                action="Collecting results",
                refresh=controller._journal_refresh,
            )
        res_col = controller.executor.run_playbook(
            controller.config.remote_execution.collect_playbook,
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
            refresh=controller._journal_refresh,
        )
    else:
        backfill_timings_from_results(
            state.active_journal,
            state.journal_file,
            pending_hosts,
            test_name,
            state.per_host_output,
            refresh=controller._journal_refresh,
        )
        phases[f"collect_{test_name}"] = ExecutionResult(
            rc=0, status="skipped", stats={}
        )
        if not controller._use_progress_stream:
            update_all_reps(
                controller.config.repetitions,
                state.active_journal,
                state.journal_file,
                pending_hosts,
                test_name,
                status,
                action="Done",
                refresh=controller._journal_refresh,
            )


def run_teardown_playbook(
    controller: "BenchmarkController",
    plugin: Any,
    inventory: InventorySpec,
    extravars: Dict[str, Any],
) -> None:
    """Execute per-workload teardown playbook when configured."""
    teardown_pb = plugin.get_ansible_teardown_path()
    if not teardown_pb:
        return
    td_extravars = extravars.copy()
    try:
        td_extravars.update(plugin.get_ansible_teardown_extravars())
    except Exception as exc:  # pragma: no cover - defensive
        teardown_logger.debug(
            "Failed to compute teardown extravars for %s: %s",
            plugin.name,
            exc,
        )
    teardown_logger.info("Executing teardown playbook for %s", plugin.name)
    controller.executor.run_playbook(
        teardown_pb,
        inventory=inventory,
        extravars=td_extravars,
        cancellable=False,
    )


def run_global_teardown(
    controller: "BenchmarkController",
    state: "_RunState",
    phases: Dict[str, ExecutionResult],
    flags: "_RunFlags",
    ui_log: Callable[[str], None],
) -> None:
    """Execute global teardown playbook if enabled."""
    if not controller.config.remote_execution.run_teardown:
        return
    stopping_now = controller._stop_requested()
    if stopping_now and controller.state_machine.state not in {
        ControllerState.STOPPING_TEARDOWN,
        ControllerState.STOPPING_INTERRUPT_TEARDOWN,
    }:
        controller._transition(
            ControllerState.STOPPING_TEARDOWN, reason="teardown after stop"
        )
    elif not stopping_now and controller.state_machine.state not in {
        ControllerState.STOPPING_TEARDOWN,
        ControllerState.STOPPING_INTERRUPT_TEARDOWN,
    }:
        controller._transition(ControllerState.RUNNING_GLOBAL_TEARDOWN)
    controller.lifecycle.start_phase(RunPhase.GLOBAL_TEARDOWN)
    if flags.stop_protocol_attempted and not flags.stop_successful:
        ui_log("Stop protocol failed/timed out; proceeding with best-effort teardown.")
        phases["stop_protocol"] = ExecutionResult(rc=1, status="failed", stats={})

    ui_log("Phase: Global Teardown")
    if controller.output_formatter:
        controller.output_formatter.set_phase("Global Teardown")
    teardown_logger.info("Executing global teardown playbook")

    if not controller.config.remote_execution.teardown_playbook:
        ui_log("No teardown playbook configured.")
        return

    if controller._stop_requested():
        controller.lifecycle.arm_stop()
        controller.lifecycle.mark_interrupting_teardown()
        controller._transition(
            ControllerState.STOPPING_INTERRUPT_TEARDOWN,
            reason="stop during teardown",
        )
        controller._interrupt_executor()
    phases["teardown_global"] = controller.executor.run_playbook(
        controller.config.remote_execution.teardown_playbook,
        inventory=state.inventory,
        extravars=state.extravars,
        cancellable=False,
    )
    if not phases["teardown_global"].success:
        ui_log("Global teardown failed to clean up perfectly.")


def run_for_hosts(
    controller: "BenchmarkController",
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
    return controller.executor.run_playbook(
        playbook_path,
        inventory=target_inventory,
        extravars=extravars,
        tags=tags,
        limit_hosts=limit_hosts,
    )
