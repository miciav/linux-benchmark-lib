"""Helper functions for controller playbook execution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lb_controller.models.state import ControllerState
from lb_controller.services.journal import RunStatus
from lb_controller.services.journal_sync import (
    backfill_timings_from_results,
    update_all_reps,
)
from lb_controller.engine.lifecycle import RunPhase
from lb_controller.engine.run_state import RunFlags, RunState
from lb_controller.models.types import (
    ExecutionResult,
    InventorySpec,
    RunExecutionSummary,
)
from lb_plugins.api import PluginAssetConfig
from lb_runner.api import RemoteHostConfig
from lb_controller.services.services import ControllerServices
from lb_controller.engine.session import RunSession
from lb_controller.engine.stop_logic import handle_stop_during_workloads

logger = logging.getLogger(__name__)
setup_logger = logging.LoggerAdapter(logger, {"lb_phase": "setup"})
teardown_logger = logging.LoggerAdapter(logger, {"lb_phase": "teardown"})


def _stop_requested(services: ControllerServices, session: RunSession) -> bool:
    if services.stop_token and services.stop_token.should_stop():
        session.arm_stop("stop requested")
        return True
    return False


def _interrupt_executor(services: ControllerServices) -> None:
    if hasattr(services.executor, "interrupt"):
        try:
            services.executor.interrupt()
        except Exception:
            pass


def _refresh_journal(services: ControllerServices) -> None:
    if services.journal_refresh:
        try:
            services.journal_refresh()
        except Exception as exc:
            logger.debug("Journal refresh callback failed: %s", exc)


def build_summary(
    services: ControllerServices,
    session: RunSession,
    phases: Dict[str, ExecutionResult],
    flags: RunFlags,
    success_override: Optional[bool] = None,
) -> RunExecutionSummary:
    if _stop_requested(services, session):
        final_state = (
            ControllerState.STOP_FAILED
            if not flags.stop_successful
            else ControllerState.ABORTED
        )
    elif not flags.all_tests_success or success_override is False:
        final_state = ControllerState.FAILED
    else:
        final_state = ControllerState.FINISHED
    session.transition(final_state)
    success = (
        success_override
        if success_override is not None
        else flags.all_tests_success and flags.stop_successful
    )
    return RunExecutionSummary(
        run_id=session.state.resolved_run_id,
        per_host_output=session.state.per_host_output,
        phases=phases,
        success=bool(success),
        output_root=session.state.output_root,
        report_root=session.state.report_root,
        data_export_root=session.state.data_export_root,
        controller_state=session.state_machine.state,
        cleanup_allowed=session.state_machine.allows_cleanup(),
    )


def run_global_setup(
    services: ControllerServices,
    session: RunSession,
    phases: Dict[str, ExecutionResult],
    flags: RunFlags,
    ui_log: Callable[[str], None],
) -> RunExecutionSummary | None:
    """Run the global setup playbook and return early summary when needed."""
    if _stop_requested(services, session):
        ui_log("Stop requested before setup; arming stop and skipping workloads.")
        services.lifecycle.arm_stop()
        services.lifecycle.mark_interrupting_setup()
        session.transition(
            ControllerState.STOPPING_INTERRUPT_SETUP,
            reason="stop before setup",
        )
        session.state.test_types = []
        return None

    ui_log("Phase: Global Setup")
    if services.output_formatter:
        services.output_formatter.set_phase("Global Setup")
    setup_logger.info("Executing global setup playbook")
    phases["setup_global"] = services.executor.run_playbook(
        services.config.remote_execution.setup_playbook,
        inventory=session.state.inventory,
        extravars=session.state.extravars,
    )
    if _stop_requested(services, session):
        services.lifecycle.arm_stop()
        services.lifecycle.mark_interrupting_setup()
        session.transition(
            ControllerState.STOPPING_INTERRUPT_SETUP,
            reason="stop during setup",
        )
        _interrupt_executor(services)
        flags.all_tests_success = False
        try:
            phases["setup_global"].status = "stopped"
        except Exception:
            pass
        session.state.test_types = []
        return None

    if not phases["setup_global"].success:
        ui_log("Global setup failed. Aborting run.")
        session.transition(ControllerState.FAILED, reason="global setup failed")
        _refresh_journal(services)
        return _build_summary(services, session, phases, flags, success_override=False)
    return None


def run_workload_setup(
    services: ControllerServices,
    session: RunSession,
    test_name: str,
    plugin_assets: PluginAssetConfig | None,
    plugin_name: str,
    inventory: InventorySpec,
    extravars: Dict[str, Any],
    pending_reps: Dict[str, List[int]],
    phases: Dict[str, ExecutionResult],
    flags: RunFlags,
    ui_log: Callable[[str], None],
) -> None:
    """Execute per-workload setup playbook."""
    setup_pb = plugin_assets.setup_playbook if plugin_assets else None
    if not setup_pb:
        phases[f"setup_{test_name}"] = ExecutionResult(
            rc=0, status="skipped", stats={}
        )
        return
    ui_log(f"Setup: {test_name} ({plugin_name})")
    if services.output_formatter:
        services.output_formatter.set_phase(f"Setup: {test_name}")
    setup_extravars = extravars.copy()
    if plugin_assets:
        setup_extravars.update(plugin_assets.setup_extravars)
    setup_logger.info("Executing setup playbook for %s (%s)", test_name, plugin_name)
    res = services.executor.run_playbook(
        setup_pb,
        inventory=inventory,
        extravars=setup_extravars,
    )
    phases[f"setup_{test_name}"] = res
    if not res.success:
        ui_log(f"Setup failed for {test_name} (rc={res.rc}, status={res.status})")
        flags.all_tests_success = False
        run_teardown_playbook(
            services, plugin_assets, plugin_name, inventory, extravars
        )
        pending_reps.clear()


def run_workload_execution(
    services: ControllerServices,
    session: RunSession,
    test_name: str,
    plugin_assets: PluginAssetConfig | None,
    plugin_name: str,
    state: RunState,
    pending_hosts: List[RemoteHostConfig],
    pending_reps: Dict[str, List[int]],
    phases: Dict[str, ExecutionResult],
    flags: RunFlags,
    ui_log: Callable[[str], None],
) -> None:
    """Execute run/collect/teardown for a workload."""
    if not pending_reps:
        return
    try:
        execute_run_playbook(
            services,
            session,
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
                services,
                session,
                test_name,
                pending_hosts,
                state,
                phases,
                flags,
                ui_log,
            )
        except Exception as exc:
            ui_log(f"Collect failed for {test_name}: {exc}")
    if services.stop_token and services.stop_token.should_stop():
        handle_stop_during_workloads(
            services, session, state.inventory, state.extravars, flags, ui_log
        )
        return
    run_teardown_playbook(
        services,
        plugin_assets,
        plugin_name,
        state.inventory,
        state.extravars,
    )


def execute_run_playbook(
    services: ControllerServices,
    session: RunSession,
    test_name: str,
    pending_hosts: List[RemoteHostConfig],
    pending_reps: Dict[str, List[int]],
    state: RunState,
    phases: Dict[str, ExecutionResult],
    flags: RunFlags,
    ui_log: Callable[[str], None],
) -> None:
    """Run the workload execution playbook and update journal status."""
    _announce_run_phase(services, test_name, pending_hosts, ui_log)
    _update_reps_for_run(
        services,
        state,
        pending_hosts,
        test_name,
        RunStatus.RUNNING,
        action="Running workload...",
    )
    loop_extravars = _build_run_extravars(state, test_name, pending_reps)
    res_run = services.executor.run_playbook(
        services.config.remote_execution.run_playbook,
        inventory=state.inventory,
        extravars=loop_extravars,
    )
    phases[f"run_{test_name}"] = res_run
    status = RunStatus.COMPLETED if res_run.success else RunStatus.FAILED

    _update_reps_for_run(
        services,
        state,
        pending_hosts,
        test_name,
        status,
        action="Completed" if res_run.success else "Failed",
        error=None if res_run.success else "ansible-playbook failed",
    )

    if not res_run.success:
        ui_log(f"Run failed for {test_name}")
        flags.all_tests_success = False


def handle_collect_phase(
    services: ControllerServices,
    session: RunSession,
    test_name: str,
    pending_hosts: List[RemoteHostConfig],
    state: RunState,
    phases: Dict[str, ExecutionResult],
    flags: RunFlags,
    ui_log: Callable[[str], None],
    plugin_assets: Optional[PluginAssetConfig] = None,
    plugin_name: Optional[str] = None,
) -> None:
    """Execute the collect playbook and backfill timings."""
    res_run = phases.get(f"run_{test_name}")
    status = RunStatus.COMPLETED if res_run and res_run.success else RunStatus.FAILED
    if services.config.remote_execution.run_collect:
        _run_collect_playbook(
            services,
            state,
            pending_hosts,
            test_name,
            status,
            phases,
            ui_log,
        )
    else:
        _skip_collect_phase(
            services, state, pending_hosts, test_name, status, phases
        )


def _announce_run_phase(
    services: ControllerServices,
    test_name: str,
    pending_hosts: List[RemoteHostConfig],
    ui_log: Callable[[str], None],
) -> None:
    ui_log(f"Run: {test_name} on {len(pending_hosts)} host(s)")
    if services.output_formatter:
        services.output_formatter.set_phase(f"Run: {test_name}")


def _update_reps_for_run(
    services: ControllerServices,
    state: RunState,
    pending_hosts: List[RemoteHostConfig],
    test_name: str,
    status: RunStatus,
    *,
    action: str,
    error: str | None = None,
) -> None:
    if services.use_progress_stream:
        return
    update_all_reps(
        services.config.repetitions,
        state.active_journal,
        state.journal_file,
        pending_hosts,
        test_name,
        status,
        action=action,
        error=error,
        refresh=services.journal_refresh,
    )


def _build_run_extravars(
    state: RunState,
    test_name: str,
    pending_reps: Dict[str, List[int]],
) -> Dict[str, Any]:
    loop_extravars = state.extravars.copy()
    loop_extravars["tests"] = [test_name]
    loop_extravars["pending_repetitions"] = pending_reps
    return loop_extravars


def _run_collect_playbook(
    services: ControllerServices,
    state: RunState,
    pending_hosts: List[RemoteHostConfig],
    test_name: str,
    status: RunStatus,
    phases: Dict[str, ExecutionResult],
    ui_log: Callable[[str], None],
) -> None:
    ui_log(f"Collect: {test_name}")
    if services.output_formatter:
        services.output_formatter.set_phase(f"Collect: {test_name}")
    _update_reps_for_run(
        services,
        state,
        pending_hosts,
        test_name,
        status,
        action="Collecting results",
    )
    res_col = services.executor.run_playbook(
        services.config.remote_execution.collect_playbook,
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
        refresh=services.journal_refresh,
    )


def _skip_collect_phase(
    services: ControllerServices,
    state: RunState,
    pending_hosts: List[RemoteHostConfig],
    test_name: str,
    status: RunStatus,
    phases: Dict[str, ExecutionResult],
) -> None:
    backfill_timings_from_results(
        state.active_journal,
        state.journal_file,
        pending_hosts,
        test_name,
        state.per_host_output,
        refresh=services.journal_refresh,
    )
    phases[f"collect_{test_name}"] = ExecutionResult(rc=0, status="skipped", stats={})
    _update_reps_for_run(
        services,
        state,
        pending_hosts,
        test_name,
        status,
        action="Done",
    )


def run_teardown_playbook(
    services: ControllerServices,
    plugin_assets: PluginAssetConfig | None,
    plugin_name: str,
    inventory: InventorySpec,
    extravars: Dict[str, Any],
) -> None:
    """Execute per-workload teardown playbook when configured."""
    teardown_pb = plugin_assets.teardown_playbook if plugin_assets else None
    if not teardown_pb:
        return
    td_extravars = extravars.copy()
    if plugin_assets:
        td_extravars.update(plugin_assets.teardown_extravars)
    teardown_logger.info("Executing teardown playbook for %s", plugin_name)
    services.executor.run_playbook(
        teardown_pb,
        inventory=inventory,
        extravars=td_extravars,
        cancellable=False,
    )


def run_global_teardown(
    services: ControllerServices,
    session: RunSession,
    state: RunState,
    phases: Dict[str, ExecutionResult],
    flags: RunFlags,
    ui_log: Callable[[str], None],
) -> None:
    """Execute global teardown playbook if enabled."""
    _ensure_global_teardown_state(session)
    if not services.config.remote_execution.run_teardown:
        return
    stopping_now = _stop_requested(services, session)
    _transition_teardown_state(session, stopping_now)
    services.lifecycle.start_phase(RunPhase.GLOBAL_TEARDOWN)
    _maybe_record_stop_protocol_failure(flags, phases, ui_log)
    _announce_teardown_phase(services, ui_log)

    if not services.config.remote_execution.teardown_playbook:
        ui_log("No teardown playbook configured.")
        return

    _maybe_interrupt_teardown(services, session)
    phases["teardown_global"] = services.executor.run_playbook(
        services.config.remote_execution.teardown_playbook,
        inventory=state.inventory,
        extravars=state.extravars,
        cancellable=False,
    )
    if not phases["teardown_global"].success:
        ui_log("Global teardown failed to clean up perfectly.")


def run_for_hosts(
    services: ControllerServices,
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
    return services.executor.run_playbook(
        playbook_path,
        inventory=target_inventory,
        extravars=extravars,
        tags=tags,
        limit_hosts=limit_hosts,
    )


def _ensure_global_teardown_state(session: RunSession) -> None:
    # Always transition to RUNNING_GLOBAL_TEARDOWN to maintain valid state flow.
    # This allows FINISHED to be reached via RUNNING_WORKLOADS ->
    # RUNNING_GLOBAL_TEARDOWN -> FINISHED.
    if session.state_machine.state == ControllerState.RUNNING_WORKLOADS:
        session.transition(ControllerState.RUNNING_GLOBAL_TEARDOWN)


def _transition_teardown_state(session: RunSession, stopping_now: bool) -> None:
    stop_states = {
        ControllerState.STOPPING_TEARDOWN,
        ControllerState.STOPPING_INTERRUPT_TEARDOWN,
    }
    if session.state_machine.state in stop_states:
        return
    if stopping_now:
        session.transition(
            ControllerState.STOPPING_TEARDOWN,
            reason="teardown after stop",
        )
        return
    session.transition(ControllerState.RUNNING_GLOBAL_TEARDOWN)


def _maybe_record_stop_protocol_failure(
    flags: RunFlags,
    phases: Dict[str, ExecutionResult],
    ui_log: Callable[[str], None],
) -> None:
    if not flags.stop_protocol_attempted or flags.stop_successful:
        return
    ui_log("Stop protocol failed/timed out; proceeding with best-effort teardown.")
    phases["stop_protocol"] = ExecutionResult(rc=1, status="failed", stats={})


def _announce_teardown_phase(
    services: ControllerServices, ui_log: Callable[[str], None]
) -> None:
    ui_log("Phase: Global Teardown")
    if services.output_formatter:
        services.output_formatter.set_phase("Global Teardown")
    teardown_logger.info("Executing global teardown playbook")


def _maybe_interrupt_teardown(
    services: ControllerServices, session: RunSession
) -> None:
    if not _stop_requested(services, session):
        return
    services.lifecycle.arm_stop()
    services.lifecycle.mark_interrupting_teardown()
    session.transition(
        ControllerState.STOPPING_INTERRUPT_TEARDOWN,
        reason="stop during teardown",
    )
    _interrupt_executor(services)
