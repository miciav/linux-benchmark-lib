"""Controller module coordinating remote benchmark execution via Ansible.

This module keeps orchestration logic inside Python while delegating remote
execution to Ansible Runner.
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Tuple
import sys

from .benchmark_config import BenchmarkConfig, RemoteHostConfig
from .journal import RunJournal, RunStatus
from .services.plugin_service import create_registry

logger = logging.getLogger(__name__)
ANSIBLE_ROOT = Path(__file__).resolve().parent / "ansible"


@dataclass
class InventorySpec:
    """Inventory specification for Ansible execution."""

    hosts: List[RemoteHostConfig]
    inventory_path: Optional[Path] = None


@dataclass
class ExecutionResult:
    """Result of a single Ansible playbook execution."""

    rc: int
    status: str
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Return True when the playbook completed successfully."""
        return self.rc == 0


@dataclass
class RunExecutionSummary:
    """Summary of a complete controller run."""

    run_id: str
    per_host_output: Dict[str, Path]
    phases: Dict[str, ExecutionResult]
    success: bool
    output_root: Path
    report_root: Path
    data_export_root: Path


class RemoteExecutor(Protocol):
    """Protocol for remote execution engines."""

    def run_playbook(
        self,
        playbook_path: Path,
        inventory: InventorySpec,
        extravars: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        limit_hosts: Optional[List[str]] = None,
    ) -> ExecutionResult:
        """Execute a playbook and return the result."""
        raise NotImplementedError


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
        envvars = {
            "ANSIBLE_ROLES_PATH": f"{runner_roles}:{repo_roles}",
            "ANSIBLE_LOCAL_TEMP": str(self.local_tmp),
            "ANSIBLE_REMOTE_TMP": "/tmp/.ansible",
            "ANSIBLE_CONFIG": str((ANSIBLE_ROOT / "ansible.cfg").resolve()),
            # Force safe stdout callback; ansible-runner's awx_display is broken with newer ansible-core.
            "ANSIBLE_STDOUT_CALLBACK": "default",
            "ANSIBLE_CALLBACK_PLUGINS": "",
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
        inventory_file.write_text(self._render_inventory(inventory.hosts))
        return inventory_file

    @staticmethod
    def _render_inventory(hosts: List[RemoteHostConfig]) -> str:
        """Render an INI inventory from host configs."""
        lines = ["[all]"]
        for host in hosts:
            lines.append(host.ansible_host_line())
        lines.append("")
        lines.append("[cluster]")
        for host in hosts:
            lines.append(host.ansible_host_line())
        return "\n".join(lines) + "\n"

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


class BenchmarkController:
    """Controller coordinating remote benchmark runs."""

    def __init__(
        self,
        config: BenchmarkConfig,
        executor: Optional[RemoteExecutor] = None,
        output_callback: Optional[Callable[[str, str], None]] = None,
        output_formatter: Optional[Any] = None,  # Inject the formatter instance
        journal_refresh: Optional[Callable[[], None]] = None,
    ):
        self.config = config
        self.output_formatter = output_formatter
        # Enable streaming if a callback is provided
        stream = output_callback is not None
        self.executor = executor or AnsibleRunnerExecutor(
            output_callback=output_callback,
            stream_output=stream
        )
        self.plugin_registry = create_registry()
        self._journal_refresh = journal_refresh

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
            journal.run_id if journal is not None else run_id or self._generate_run_id()
        )
        inventory = InventorySpec(
            hosts=self.config.remote_hosts,
            inventory_path=self.config.remote_execution.inventory_path,
        )

        output_root, report_root, data_export_root = self._prepare_run_dirs(
            resolved_run_id
        )
        per_host_output = self._prepare_per_host_dirs(
            output_root=output_root, report_root=report_root
        )

        active_journal = journal or RunJournal.initialize(
            resolved_run_id, self.config, test_types
        )
        journal_file = journal_path or output_root / "run_journal.json"
        active_journal.save(journal_file)
        self._refresh_journal()

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
            "benchmark_config": self.config.to_dict(),
            "use_container_fallback": self.config.remote_execution.use_container_fallback,
            "collector_apt_packages": sorted(self._collector_apt_packages()),
            "workload_runner_install_deps": False,  # Dependencies are now handled by per-plugin setup
            # Let the workload runner handle all repetitions in one go.
            "repetitions_total": self.config.repetitions,
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
                for rep in range(1, self.config.repetitions + 1):
                    if active_journal.should_run(host.name, test_name, rep):
                        hosts.append(host)
                        break
            return hosts

        ui_log(f"Starting Run {resolved_run_id}")

        # 1. Global Setup
        if self.config.remote_execution.run_setup:
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
            pending_hosts = _pending_hosts_for(test_name)
            if not pending_hosts:
                ui_log(f"All repetitions already completed for {test_name}, skipping.")
                continue

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
            self._update_all_reps(
                active_journal,
                journal_file,
                pending_hosts,
                test_name,
                RunStatus.RUNNING,
                action="Running workload...",
            )

            loop_extravars = extravars.copy()
            loop_extravars["tests"] = [test_name]

            res_run = self.executor.run_playbook(
                self.config.remote_execution.run_playbook,
                inventory=inventory,
                extravars=loop_extravars,
            )
            phases[f"run_{test_name}"] = res_run
            status = RunStatus.COMPLETED if res_run.success else RunStatus.FAILED

            self._update_all_reps(
                active_journal,
                journal_file,
                pending_hosts,
                test_name,
                status,
                action="Completed" if res_run.success else "Failed",
                error=None if res_run.success else "ansible-playbook failed",
            )

            if not res_run.success:
                ui_log(f"Run failed for {test_name}")
                all_tests_success = False

            # C. Intermediate Collect (single sync)
            if self.config.remote_execution.run_collect:
                ui_log(f"Collect: {test_name}")
                if self.output_formatter:
                    self.output_formatter.set_phase(f"Collect: {test_name}")
                self._update_all_reps(
                    active_journal,
                    journal_file,
                    pending_hosts,
                    test_name,
                    status,
                    action="Collecting results",
                )
                res_col = self.executor.run_playbook(
                    self.config.remote_execution.collect_playbook,
                    inventory=inventory,
                    extravars=extravars,
                )
                phases[f"collect_{test_name}"] = res_col
                self._backfill_timings_from_results(
                    active_journal,
                    journal_file,
                    pending_hosts,
                    test_name,
                    per_host_output,
                )
            else:
                # If collect is disabled, still try to backfill from any locally available results.
                self._backfill_timings_from_results(
                    active_journal,
                    journal_file,
                    pending_hosts,
                    test_name,
                    per_host_output,
                )
                phases["collect"] = res_col
                self._update_all_reps(
                    active_journal,
                    journal_file,
                    pending_hosts,
                    test_name,
                    status,
                    action="Done",
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

    def _update_journal_tasks(
        self,
        journal: RunJournal,
        journal_path: Path,
        hosts: List[RemoteHostConfig],
        workload: str,
        repetition: int,
        status: str,
        action: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update journal entries for each host and persist."""
        for host in hosts:
            journal.update_task(
                host.name,
                workload,
                repetition,
                status,
                action=action,
                error=error,
            )
        journal.save(journal_path)
        self._refresh_journal()

    def _backfill_timings_from_results(
        self,
        journal: RunJournal,
        journal_path: Path,
        hosts: List[RemoteHostConfig],
        workload: str,
        per_host_output: Dict[str, Path],
    ) -> None:
        """Backfill per-repetition timing data from *_results.json artifacts."""
        updated = False
        for host in hosts:
            host_dir = per_host_output.get(host.name)
            if not host_dir:
                continue
            results_file = host_dir / f"{workload}_results.json"
            if not results_file.exists():
                continue
            try:
                entries = json.loads(results_file.read_text())
            except Exception as exc:
                logger.debug("Failed to parse results for %s: %s", host.name, exc)
                continue
            for entry in entries or []:
                rep = entry.get("repetition")
                if rep is None:
                    continue
                task = journal.get_task(host.name, workload, rep)
                if not task:
                    continue
                try:
                    start_str = entry.get("start_time")
                    end_str = entry.get("end_time")
                    if start_str:
                        task.started_at = datetime.fromisoformat(start_str).timestamp()
                    if end_str:
                        task.finished_at = datetime.fromisoformat(end_str).timestamp()
                    duration = entry.get("duration_seconds")
                    if duration is not None:
                        task.duration_seconds = float(duration)
                    elif task.started_at is not None and task.finished_at is not None:
                        task.duration_seconds = max(0.0, task.finished_at - task.started_at)
                    updated = True
                except Exception as exc:
                    logger.debug("Failed to backfill timing for %s rep %s: %s", host.name, rep, exc)
        if updated:
            journal.save(journal_path)
            self._refresh_journal()

    def _update_all_reps(
        self,
        journal: RunJournal,
        journal_path: Path,
        hosts: List[RemoteHostConfig],
        workload: str,
        status: str,
        action: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update journal for all repetitions of a workload."""
        if not journal:
            return
        for rep in range(1, self.config.repetitions + 1):
            self._update_journal_tasks(
                journal,
                journal_path,
                hosts,
                workload,
                rep,
                status,
                action=action,
                error=error,
            )

    def _refresh_journal(self) -> None:
        """Trigger UI refresh when a journal update occurs."""
        if self._journal_refresh:
            self._journal_refresh()

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a monotonic timestamp-based run identifier."""
        return datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")

    def _prepare_run_dirs(
        self,
        run_id: str,
    ) -> tuple[Path, Path, Path]:
        """Create base directories for a run."""
        output_root = (self.config.output_dir / run_id).resolve()
        report_root = (self.config.report_dir / run_id).resolve()
        data_export_root = (self.config.data_export_dir / run_id).resolve()
        for path in (output_root, report_root, data_export_root):
            path.mkdir(parents=True, exist_ok=True)
        return output_root, report_root, data_export_root

    def _prepare_per_host_dirs(
        self,
        output_root: Path,
        report_root: Path,
    ) -> Dict[str, Path]:
        """Prepare output/report directories per host."""
        per_host: Dict[str, Path] = {}
        for host in self.config.remote_hosts:
            host_report_dir = report_root / host.name
            host_dir = output_root / host.name
            host_dir.mkdir(parents=True, exist_ok=True)
            host_report_dir.mkdir(parents=True, exist_ok=True)
            per_host[host.name] = host_dir
        return per_host
