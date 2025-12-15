"""Controller module coordinating remote benchmark execution via Ansible.

This module keeps orchestration logic inside Python while delegating remote
execution to Ansible Runner.
"""

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from lb_runner.benchmark_config import BenchmarkConfig, RemoteHostConfig
from lb_runner.stop_token import StopToken

from lb_controller.ansible_executor import AnsibleRunnerExecutor
from lb_controller.journal import RunJournal, RunStatus
from lb_controller.journal_sync import (
    backfill_timings_from_results,
    update_all_reps,
)
from lb_controller.paths import generate_run_id, prepare_per_host_dirs, prepare_run_dirs
from lb_controller.services.plugin_service import create_registry
from lb_controller.types import (
    ExecutionResult,
    InventorySpec,
    RemoteExecutor,
    RunExecutionSummary,
)

logger = logging.getLogger(__name__)


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
    ):
        self.config = config
        self.output_formatter = output_formatter
        self.stop_token = stop_token
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

        resolved_run_id = (
            journal.run_id if journal is not None else run_id or generate_run_id()
        )
        inventory = InventorySpec(
            hosts=self.config.remote_hosts,
            inventory_path=self.config.remote_execution.inventory_path,
        )

        target_reps = (
            (journal.metadata.get("repetitions") if journal else None)
            or self.config.repetitions
        )

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

        # Default remote output root to a temp dir with run_id
        # This avoids using local paths on remote hosts
        remote_output_root = f"/tmp/benchmark_results/{resolved_run_id}"

        extravars = {
            "run_id": resolved_run_id,
            # 'tests' will be overridden per loop iteration
            "output_root": str(output_root),
            "remote_output_root": remote_output_root,
            "report_root": str(report_root),
            "data_export_root": str(data_export_root),
            "lb_workdir": "/opt/lb",
            "per_host_output": {k: str(v) for k, v in per_host_output.items()},
            "benchmark_config": self.config.model_dump(mode="json"),
            "use_container_fallback": self.config.remote_execution.use_container_fallback,
            "collector_apt_packages": sorted(self._collector_apt_packages()),
            "workload_runner_install_deps": False,  # Dependencies are now handled by per-plugin setup
            # Let the workload runner handle all repetitions in one go.
            "repetitions_total": target_reps,
            "repetition_index": 0,
        }
        phases: Dict[str, ExecutionResult] = {}

        # Helper for logging - purely backend logging now, UI is handled by callback
        def ui_log(msg: str):
            logger.info(msg)

        def _pending_hosts_for(test_name: str) -> List[RemoteHostConfig]:
            if not active_journal:
                return self.config.remote_hosts
            hosts: List[RemoteHostConfig] = []
            for host in self.config.remote_hosts:
                for rep in range(1, target_reps + 1):
                    if active_journal.should_run(host.name, test_name, rep):
                        hosts.append(host)
                        break
            return hosts

        ui_log(f"Starting Run {resolved_run_id}")

        # 1. Global Setup
        if self.config.remote_execution.run_setup:
            if self.stop_token and self.stop_token.should_stop():
                ui_log("Stop requested before setup; aborting run after teardown.")
                # Defer to teardown section for cleanup.
            else:
                ui_log("Phase: Global Setup")
                if self.output_formatter:
                    self.output_formatter.set_phase("Global Setup")
                phases["setup_global"] = self.executor.run_playbook(
                    self.config.remote_execution.setup_playbook,
                    inventory=inventory,
                    extravars=extravars,
                )
                if not phases["setup_global"].success:
                    ui_log("Global setup failed. Aborting run.")
                    self._refresh_journal()
                    return RunExecutionSummary(
                        run_id=resolved_run_id,
                        per_host_output=per_host_output,
                        phases=phases,
                        success=False,
                        output_root=output_root,
                        report_root=report_root,
                        data_export_root=data_export_root,
                    )
        # 2. Per-Test Loop (single Ansible run per workload; LocalRunner handles repetitions)
        all_tests_success = True
        for test_name in test_types:
            if self.stop_token and self.stop_token.should_stop():
                ui_log("Stop requested; draining teardown...")
                all_tests_success = False
                break
            workload_cfg = self.config.workloads.get(test_name)
            if not workload_cfg:
                ui_log(f"Skipping unknown workload: {test_name}")
                continue

            try:
                plugin = self.plugin_registry.get(workload_cfg.plugin)
            except Exception as e:
                ui_log(f"Failed to load plugin for {test_name}: {e}")
                all_tests_success = False
                continue
            if self.stop_token and self.stop_token.should_stop():
                all_tests_success = False
                break
            pending_hosts = _pending_hosts_for(test_name)
            if not pending_hosts:
                ui_log(f"All repetitions already completed for {test_name}, skipping.")
                continue
            # Compute pending repetitions per host for finer-grained skip.
            pending_reps: Dict[str, List[int]] = {}
            for host in pending_hosts:
                reps_for_host: List[int] = []
                for rep in range(1, target_reps + 1):
                    if active_journal.should_run(host.name, test_name, rep):
                        reps_for_host.append(rep)
                pending_reps[host.name] = reps_for_host or [1]

            # A. Plugin Setup
            setup_pb = plugin.get_ansible_setup_path()
            if setup_pb:
                ui_log(f"Setup: {test_name} ({plugin.name})")
                if self.output_formatter:
                    self.output_formatter.set_phase(f"Setup: {test_name}")
                res = self.executor.run_playbook(setup_pb, inventory=inventory, extravars=extravars)
                phases[f"setup_{test_name}"] = res
                if not res.success:
                    ui_log(f"Setup failed for {test_name}")
                    all_tests_success = False
                    teardown_pb = plugin.get_ansible_teardown_path()
                    if teardown_pb:
                        self.executor.run_playbook(teardown_pb, inventory=inventory, extravars=extravars)
                    continue

            # B. Run Workload (single call covers all repetitions)
            ui_log(f"Run: {test_name} on {len(pending_hosts)} host(s)")
            if self.output_formatter:
                self.output_formatter.set_phase(f"Run: {test_name}")
            if not self._use_progress_stream:
                update_all_reps(
                    self.config.repetitions,
                    active_journal,
                    journal_file,
                    pending_hosts,
                    test_name,
                    RunStatus.RUNNING,
                    action="Running workload...",
                    refresh=self._journal_refresh,
                )

            loop_extravars = extravars.copy()
            loop_extravars["tests"] = [test_name]
            loop_extravars["pending_repetitions"] = pending_reps

            res_run = self.executor.run_playbook(
                self.config.remote_execution.run_playbook,
                inventory=inventory,
                extravars=loop_extravars,
            )
            phases[f"run_{test_name}"] = res_run
            status = RunStatus.COMPLETED if res_run.success else RunStatus.FAILED

            if not self._use_progress_stream:
                update_all_reps(
                    self.config.repetitions,
                    active_journal,
                    journal_file,
                    pending_hosts,
                    test_name,
                    status,
                    action="Completed" if res_run.success else "Failed",
                    error=None if res_run.success else "ansible-playbook failed",
                    refresh=self._journal_refresh,
                )

            if not res_run.success:
                ui_log(f"Run failed for {test_name}")
                all_tests_success = False

            # C. Intermediate Collect (single sync)
            if self.stop_token and self.stop_token.should_stop():
                all_tests_success = False
            elif self.config.remote_execution.run_collect:
                ui_log(f"Collect: {test_name}")
                if self.output_formatter:
                    self.output_formatter.set_phase(f"Collect: {test_name}")
                if not self._use_progress_stream:
                    update_all_reps(
                        self.config.repetitions,
                        active_journal,
                        journal_file,
                        pending_hosts,
                        test_name,
                        status,
                        action="Collecting results",
                        refresh=self._journal_refresh,
                    )
                res_col = self.executor.run_playbook(
                    self.config.remote_execution.collect_playbook,
                    inventory=inventory,
                    extravars=extravars,
                )
                phases[f"collect_{test_name}"] = res_col
                backfill_timings_from_results(
                    active_journal,
                    journal_file,
                    pending_hosts,
                    test_name,
                    per_host_output,
                    refresh=self._journal_refresh,
                )
            else:
                # If collect is disabled, still try to backfill from any locally available results.
                backfill_timings_from_results(
                    active_journal,
                    journal_file,
                    pending_hosts,
                    test_name,
                    per_host_output,
                    refresh=self._journal_refresh,
                )
                phases[f"collect_{test_name}"] = ExecutionResult(
                    rc=0, status="skipped", stats={}
                )
                if not self._use_progress_stream:
                    update_all_reps(
                        self.config.repetitions,
                        active_journal,
                        journal_file,
                        pending_hosts,
                        test_name,
                        status,
                        action="Done",
                        refresh=self._journal_refresh,
                    )

            # D. Plugin Teardown
            teardown_pb = plugin.get_ansible_teardown_path()
            if teardown_pb:
                ui_log(f"Teardown: {test_name}")
                if self.output_formatter:
                    self.output_formatter.set_phase(f"Teardown: {test_name}")
                res_td = self.executor.run_playbook(teardown_pb, inventory=inventory, extravars=extravars)
                phases[f"teardown_{test_name}"] = res_td
                if not res_td.success:
                    ui_log(f"Teardown failed for {test_name}")
            if self.stop_token and self.stop_token.should_stop():
                all_tests_success = False
                break

        # 3. Global Teardown (Clean up remote artifacts)
        if self.config.remote_execution.run_teardown:
            ui_log("Phase: Global Teardown")
            if self.output_formatter:
                self.output_formatter.set_phase("Global Teardown")

            if self.config.remote_execution.teardown_playbook:
                phases["teardown_global"] = self.executor.run_playbook(
                    self.config.remote_execution.teardown_playbook,
                    inventory=inventory,
                    extravars=extravars,
                )
                if not phases["teardown_global"].success:
                    ui_log("Global teardown failed to clean up perfectly.")
            else:
                ui_log("No teardown playbook configured.")

        ui_log("Run Finished.")
        time.sleep(1)

        return RunExecutionSummary(
            run_id=resolved_run_id,
            per_host_output=per_host_output,
            phases=phases,
            success=all_tests_success,
            output_root=output_root,
            report_root=report_root,
            data_export_root=data_export_root,
        )

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
