"""
Controller module coordinating remote benchmark execution via Ansible.

This module keeps orchestration logic inside Python while delegating remote
execution to Ansible Runner.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from benchmark_config import BenchmarkConfig, RemoteHostConfig
from plugins.builtin import builtin_plugins
from plugins.registry import PluginRegistry, print_plugin_table


logger = logging.getLogger(__name__)


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
    ):
        """
        Initialize the executor.

        Args:
            private_data_dir: Directory used by ansible-runner.
            runner_fn: Optional runner callable for testing. Defaults to
                ansible_runner.run when not provided.
            stream_output: When True, stream Ansible stdout events to the local
                process (useful for visibility in long-running tasks).
        """
        self.private_data_dir = private_data_dir or Path("ansible")
        self.private_data_dir.mkdir(parents=True, exist_ok=True)
        self._runner_fn = runner_fn
        self.stream_output = stream_output

    def run_playbook(
        self,
        playbook_path: Path,
        inventory: InventorySpec,
        extravars: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
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

        result = runner_fn(
            private_data_dir=str(self.private_data_dir),
            playbook=str(abs_playbook_path),
            inventory=str(inventory_path),
            extravars=merged_extravars,
            tags=",".join(tags) if tags else None,
            quiet=self.stream_output,  # suppress runner's own stdout when streaming ourselves
            event_handler=self._event_handler if self.stream_output else None,
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

    @staticmethod
    def _event_handler(event: Dict[str, Any]) -> None:
        """Stream Ansible runner stdout events to the local console."""
        import sys
        
        # 1. Handle standard runner stdout (the Ansible UI output)
        stdout = event.get("stdout")
        if stdout:
            # Check for progress marker
            if "BENCHMARK_PROGRESS:" in stdout:
                # Extract percentage and show dynamically
                try:
                    # stdout might contain other text, try to isolate the progress
                    parts = stdout.split("BENCHMARK_PROGRESS:")
                    if len(parts) > 1:
                        progress = parts[1].strip()
                        sys.stdout.write(f"\r>>> Progress: {progress}   ")
                        sys.stdout.flush()
                except Exception:
                    pass # Fallback to standard printing if parsing fails
            else:
                # Avoid printing duplicate consecutive lines sometimes emitted by runner
                last = getattr(AnsibleRunnerExecutor._event_handler, "_last_stdout", None)
                if stdout != last:
                    # If we were printing progress, move to a new line before printing normal logs
                    if getattr(AnsibleRunnerExecutor._event_handler, "_was_progress", False):
                         print("", flush=True)
                    
                    print(stdout, flush=True)
                    AnsibleRunnerExecutor._event_handler._last_stdout = stdout
                    AnsibleRunnerExecutor._event_handler._was_progress = False

            # Mark if we just printed progress so we can newline later
            if "BENCHMARK_PROGRESS:" in stdout:
                AnsibleRunnerExecutor._event_handler._was_progress = True
        
        # 2. Handle task completion events to show command output
        # "runner_on_ok" or "runner_on_failed" usually contain the module result
        if event.get("event") in ("runner_on_ok", "runner_on_failed"):
            event_data = event.get("event_data", {})
            task_name = event_data.get("task", "")
            
            # Only show detailed output for the benchmark execution task to reduce noise
            if "Run benchmark" in task_name:
                res = event_data.get("res", {})
                # Try multiple sources of output. 'stdout' is preferred for shell commands.
                task_stdout = res.get("stdout") or res.get("msg") or res.get("stderr")
                
                if task_stdout:
                     print(f"\n[Benchmark Output: {task_name}]\n{task_stdout}\n", flush=True)


class BenchmarkController:
    """Controller coordinating remote benchmark runs."""

    def __init__(
        self,
        config: BenchmarkConfig,
        executor: Optional[RemoteExecutor] = None,
    ):
        self.config = config
        self.executor = executor or AnsibleRunnerExecutor()
        self.plugin_registry = PluginRegistry(builtin_plugins())

    def run(
        self,
        test_types: List[str],
        run_id: Optional[str] = None,
    ) -> RunExecutionSummary:
        """
        Execute the configured benchmarks on remote hosts.

        Args:
            test_types: List of benchmark identifiers to execute.
            run_id: Optional run identifier. If not provided, a timestamp-based
                id is generated.
        """
        if not self.config.remote_hosts:
            raise ValueError("At least one remote host must be configured.")

        resolved_run_id = run_id or self._generate_run_id()
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

        # Default remote output root to a temp dir with run_id
        # This avoids using local paths on remote hosts
        remote_output_root = f"/tmp/benchmark_results/{resolved_run_id}"

        extravars = {
            "run_id": resolved_run_id,
            "tests": [t for t in test_types if t != "top500"],
            "output_root": str(output_root),
            "remote_output_root": remote_output_root,
            "report_root": str(report_root),
            "data_export_root": str(data_export_root),
            "per_host_output": {k: str(v) for k, v in per_host_output.items()},
            "benchmark_config": self.config.to_dict(),
            "use_container_fallback": self.config.remote_execution.use_container_fallback,
            "workload_runner_install_deps": True,
        }

        phases: Dict[str, ExecutionResult] = {}

        phases: Dict[str, ExecutionResult] = {}

        # Run top500 first if requested (controller-driven playbook)
        if "top500" in test_types:
            top500 = self.config.top500
            top500_vars = {
                "top500_repo_url": top500.repo_url,
                "top500_repo_ref": top500.repo_ref,
                "top500_workdir": str(top500.workdir),
                "top500_tags": top500.tags,
                "top500_config_overrides": top500.config_overrides,
                "top500_run_id": resolved_run_id,
            }
            phases["top500"] = self.executor.run_playbook(
                Path("ansible/playbooks/top500.yml"),
                inventory=inventory,
                extravars=top500_vars,
            )

        if extravars["tests"]:
            if self.config.remote_execution.run_setup:
                phases["setup"] = self.executor.run_playbook(
                    self.config.remote_execution.setup_playbook,
                    inventory=inventory,
                    extravars=extravars,
                )

            phases["run"] = self.executor.run_playbook(
                self.config.remote_execution.run_playbook,
                inventory=inventory,
                extravars=extravars,
            )

            if self.config.remote_execution.run_collect:
                phases["collect"] = self.executor.run_playbook(
                    self.config.remote_execution.collect_playbook,
                    inventory=inventory,
                    extravars=extravars,
                )

        success = all(result.success for result in phases.values())

        return RunExecutionSummary(
            run_id=resolved_run_id,
            per_host_output=per_host_output,
            phases=phases,
            success=success,
            output_root=output_root,
            report_root=report_root,
            data_export_root=data_export_root,
        )

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a monotonic timestamp-based run identifier."""
        return datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")

    def _prepare_run_dirs(
        self,
        run_id: str,
    ) -> tuple[Path, Path, Path]:
        """Create base directories for a run."""
        output_root = self.config.output_dir / run_id
        report_root = self.config.report_dir / run_id
        data_export_root = self.config.data_export_dir / run_id
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
            host_dir = output_root / host.name
            host_report_dir = report_root / host.name
            host_dir.mkdir(parents=True, exist_ok=True)
            host_report_dir.mkdir(parents=True, exist_ok=True)
            per_host[host.name] = host_dir
        return per_host
