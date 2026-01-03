"""Service for running workload phases."""

from __future__ import annotations

from typing import Callable, Dict

from lb_controller.adapters.playbooks import (
    run_workload_execution,
    run_workload_setup,
)
from lb_controller.engine.lifecycle import RunPhase
from lb_controller.engine.run_state import RunFlags, RunState
from lb_controller.models.pending import pending_hosts_for, pending_repetitions
from lb_controller.models.types import ExecutionResult
from lb_plugins.api import PluginAssetConfig
from lb_runner.api import BenchmarkConfig

from lb_controller.services.controller_context import ControllerContext
from lb_controller.services.ui_notifier import UINotifier


class WorkloadRunner:
    """Run workload setup and execution across configured hosts."""

    def __init__(
        self,
        config: BenchmarkConfig,
        context: ControllerContext,
        ui_notifier: UINotifier,
    ) -> None:
        self._config = config
        self._context = context
        self._ui = ui_notifier

    def run_workloads(
        self,
        state: RunState,
        phases: Dict[str, ExecutionResult],
        flags: RunFlags,
        resume_requested: bool,
        ui_log: Callable[[str], None],
    ) -> RunFlags:
        self._context.lifecycle.start_phase(RunPhase.WORKLOADS)
        for test_name in state.test_types:
            if self._context._stop_requested():
                flags = self._context._handle_stop_during_workloads(
                    state.inventory, state.extravars, flags, ui_log
                )
                break
            if not self._process_single_workload(
                test_name, state, phases, flags, resume_requested, ui_log
            ):
                break
        return flags

    def _process_single_workload(
        self,
        test_name: str,
        state: RunState,
        phases: Dict[str, ExecutionResult],
        flags: RunFlags,
        resume_requested: bool,
        ui_log: Callable[[str], None],
    ) -> bool:
        workload_cfg = self._config.workloads.get(test_name)
        if not workload_cfg:
            ui_log(f"Skipping unknown workload: {test_name}")
            return True

        pending_hosts = pending_hosts_for(
            state.active_journal,
            state.target_reps,
            test_name,
            self._config.remote_hosts,
            allow_skipped=resume_requested,
        )
        if not pending_hosts:
            ui_log(f"All repetitions already completed for {test_name}, skipping.")
            return True

        plugin_assets = self._get_plugin_assets(workload_cfg.plugin, test_name, ui_log)

        if self._context.stop_token and self._context.stop_token.should_stop():
            self._context._handle_stop_during_workloads(
                state.inventory, state.extravars, flags, ui_log
            )
            return False

        pending_reps = pending_repetitions(
            state.active_journal,
            state.target_reps,
            pending_hosts,
            test_name,
            allow_skipped=resume_requested,
        )

        run_workload_setup(
            self._context,
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
        if self._context._stop_requested():
            self._context._handle_stop_during_workloads(
                state.inventory, state.extravars, flags, ui_log
            )
            return False

        run_workload_execution(
            self._context,
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

        if self._context._stop_requested():
            self._context._handle_stop_during_workloads(
                state.inventory, state.extravars, flags, ui_log
            )
            return False
        return True

    def _get_plugin_assets(
        self,
        plugin_name: str,
        test_name: str,
        ui_log: Callable[[str], None],
    ) -> PluginAssetConfig | None:
        assets = self._config.plugin_assets.get(plugin_name)
        if assets is None:
            ui_log(
                f"No plugin assets found for {test_name} ({plugin_name}); skipping setup/teardown."
            )
        return assets
