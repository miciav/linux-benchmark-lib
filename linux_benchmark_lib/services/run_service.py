"""Application-facing run orchestration helpers for the CLI."""

from __future__ import annotations

from datetime import datetime
import re
import ctypes.util
from dataclasses import dataclass, asdict
from typing import Callable, List, Optional, Dict, Any, TYPE_CHECKING
from pathlib import Path

from ..benchmark_config import BenchmarkConfig, RemoteExecutionConfig
from ..journal import RunJournal
from ..local_runner import LocalRunner
from ..plugins.registry import PluginRegistry
from ..plugins.interface import WorkloadIntensity
from .container_service import ContainerRunner, ContainerRunSpec
from .multipass_service import MultipassService
from ..ui.console_adapter import ConsoleUIAdapter
from ..ui.run_dashboard import NoopDashboard, RunDashboard
from ..ui.types import UIAdapter

if TYPE_CHECKING:
    from ..controller import BenchmarkController, RunExecutionSummary


class AnsibleOutputFormatter:
    """Parses raw Ansible output stream and prints user-friendly status updates."""
    
    def __init__(self):
        self.task_pattern = re.compile(r"TASK \[(.*?)\]")
        self.bench_pattern = re.compile(r"Running benchmark: (.*)")
        self.current_phase = "Initializing" # Default phase
    
    def set_phase(self, phase: str):
        self.current_phase = phase

    def process(self, text: str, end: str = ""):
        if not text:
            return
        
        lines = text.splitlines()
        for line in lines:
            self._handle_line(line)

    def _handle_line(self, line: str):
        line = line.strip()
        if not line:
            return

        # Filter noise
        if any(x in line for x in ["PLAY [", "GATHERING FACTS", "RECAP", "ok:", "skipping:", "included:"]):
            return
        if line.startswith("*****"):
            return

        # Format Tasks
        task_match = self.task_pattern.search(line)
        if task_match:
            task_name = task_match.group(1).strip()
            # Cleanup "workload_runner :" prefix if present
            if " : " in task_name:
                _, task_name = task_name.split(" : ", 1)
            print(f"• [{self.current_phase}] {task_name}")
            return

        # Format Benchmark Start (from python script)
        bench_match = self.bench_pattern.search(line)
        if bench_match:
            bench_name = bench_match.group(1)
            print(f"\n>>> Benchmark: {bench_name} <<<\n")
            return

        # Format Changes (usually means success in ansible terms)
        if line.startswith("changed:"):
            return

        # Pass through interesting lines from the benchmark script
        if "linux_benchmark_lib.local_runner" in line or "Running test" in line or "Progress:" in line or "Completed" in line:
             print(f"  {line}")
             return
        
        # Pass through raw output that looks like a progress bar (rich output often has special chars)
        if "━" in line:
             print(f"  {line}")
             return

        # Pass through errors
        if "fatal:" in line or "ERROR" in line or "failed:" in line:
            print(f"[!] {line}")


@dataclass
class RunContext:
    """Inputs required to execute a run."""

    config: BenchmarkConfig
    target_tests: List[str]
    registry: PluginRegistry
    use_remote: bool
    use_container: bool = False
    use_multipass: bool = False
    config_path: Optional[Path] = None
    docker_image: str = "linux-benchmark-lib:dev"
    docker_engine: str = "docker"
    docker_build: bool = True
    docker_no_cache: bool = False
    docker_workdir: Path | None = None
    debug: bool = False
    resume_from: str | None = None
    resume_latest: bool = False


@dataclass
class RunResult:
    """Outcome of a run."""

    context: RunContext
    summary: Optional[RunExecutionSummary]


class RunService:
    """Coordinate benchmark execution for CLI commands."""

    def __init__(self, registry_factory: Callable[[], PluginRegistry]):
        self._registry_factory = registry_factory
        self._container_runner = ContainerRunner()

    def get_run_plan(
        self,
        cfg: BenchmarkConfig,
        tests: List[str],
        docker_mode: bool = False,
        multipass_mode: bool = False,
        remote_mode: bool = False,
        registry: PluginRegistry | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Build a detailed plan for the workloads to be run.
        
        Returns a list of dictionaries containing status, intensity, details, etc.
        """
        registry = registry or self._registry_factory()
        plan = []
        
        for name in tests:
            wl = cfg.workloads.get(name)
            item = {
                "name": name,
                "plugin": wl.plugin if wl else "unknown",
                "status": "[yellow]?[/yellow]",
                "intensity": wl.intensity if wl else "-",
                "details": "-",
                "repetitions": str(cfg.repetitions),
            }
            
            if not wl:
                plan.append(item)
                continue

            try:
                plugin = registry.get(wl.plugin)
            except Exception:
                item["status"] = "[red]✗ (Missing)[/red]"
                plan.append(item)
                continue

            # Resolve Configuration (Preset vs Options)
            config_obj = None
            try:
                if wl.intensity and wl.intensity != "user_defined":
                    try:
                        level = WorkloadIntensity(wl.intensity)
                        config_obj = plugin.get_preset_config(level)
                    except ValueError:
                        pass # Invalid intensity, will fall back
                
                # Fallback to user options if no preset found/used
                if config_obj is None:
                    # Instantiate config from dict
                    if isinstance(wl.options, dict):
                        config_obj = plugin.config_cls(**wl.options)
                    else:
                        config_obj = wl.options
            except Exception as e:
                item["details"] = f"[red]Config Error: {e}[/red]"

            # Format details string
            if config_obj:
                try:
                    # Convert to dict, filter None values
                    data = asdict(config_obj)
                    # Prioritize common fields for brevity
                    parts = []
                    
                    # Duration/Timeout check
                    duration = data.get("timeout") or data.get("time") or data.get("runtime")
                    if duration:
                        parts.append(f"Time: {duration}s")
                    
                    # Specific fields per plugin type
                    if "cpu_workers" in data and data["cpu_workers"] > 0:
                        parts.append(f"CPU: {data['cpu_workers']}")
                    if "vm_bytes" in data:
                        parts.append(f"VM: {data['vm_bytes']}")
                    if "bs" in data:
                        parts.append(f"BS: {data['bs']}")
                    if "count" in data and data["count"]:
                        parts.append(f"Count: {data['count']}")
                    if "parallel" in data:
                        parts.append(f"Streams: {data['parallel']}")
                    if "rw" in data:
                        parts.append(f"Mode: {data['rw']}")
                    if "iodepth" in data:
                        parts.append(f"Depth: {data['iodepth']}")
                        
                    # Fallback if specific fields didn't cover much
                    if len(parts) < 2:
                        parts = [f"{k}={v}" for k, v in data.items() if v is not None and k not in ["extra_args"]]
                    
                    item["details"] = ", ".join(parts)
                except Exception:
                    item["details"] = str(config_obj)

            if docker_mode:
                item["status"] = "[green]Container[/green]"
                plan.append(item)
                continue

            if multipass_mode:
                item["status"] = "[green]Multipass[/green]"
                plan.append(item)
                continue

            if remote_mode:
                item["status"] = "[blue]Remote[/blue]"
                plan.append(item)
                continue

            # Special-case iperf3 check
            if plugin.name == "iperf3":
                lib = ctypes.util.find_library("iperf")
                item["status"] = "[green]✓[/green]" if lib else "[red]✗ (Lib Missing)[/red]"
                plan.append(item)
                continue

            # General Environment Validation
            try:
                # Create a temporary generator just to check environment
                gen = plugin.create_generator(config_obj)
                
                # Check check_prerequisites or _validate_environment
                checker = getattr(gen, "check_prerequisites", None)
                if callable(checker):
                    is_ok = checker()
                else:
                    validator = getattr(gen, "_validate_environment", None)
                    is_ok = validator() if callable(validator) else False
                
                item["status"] = "[green]✓[/green]" if is_ok else "[red]✗ (Env Check)[/red]"
            except Exception:
                item["status"] = "[red]✗ (Init Failed)[/red]"
            
            plan.append(item)
            
        return plan

    def build_context(
        self,
        cfg: BenchmarkConfig,
        tests: Optional[List[str]],
        remote_override: Optional[bool],
        docker: bool = False,
        multipass: bool = False,
        docker_image: str = "linux-benchmark-lib:dev",
        docker_engine: str = "docker",
        docker_build: bool = True,
        docker_no_cache: bool = False,
        config_path: Optional[Path] = None,
        debug: bool = False,
        resume: Optional[str] = None,
    ) -> RunContext:
        """Compute the run context and registry."""
        registry = self._registry_factory()
        target_tests = tests or [
            name for name, workload in cfg.workloads.items() if workload.enabled
        ]
        use_remote = remote_override if remote_override is not None else cfg.remote_execution.enabled
        
        if multipass:
            use_remote = True

        # Use repo root (where Dockerfile lives) as the container build context
        project_root = Path(__file__).resolve().parent.parent.parent
        return RunContext(
            config=cfg,
            target_tests=target_tests,
            registry=registry,
            use_remote=use_remote,
            use_container=docker,
            use_multipass=multipass,
            config_path=config_path,
            docker_image=docker_image,
            docker_engine=docker_engine,
            docker_build=docker_build,
            docker_no_cache=docker_no_cache,
            docker_workdir=project_root if docker else None,
            debug=debug,
            resume_from=None if resume in (None, "latest") else resume,
            resume_latest=resume == "latest",
        )

    def execute(
        self,
        context: RunContext,
        run_id: Optional[str],
        output_callback: Optional[Callable[[str, str], None]] = None,
        ui_adapter: UIAdapter | None = None,
    ) -> RunResult:
        """Execute benchmarks using the provided context."""
        
        # Ensure we always stream output for remote/multipass to show progress
        formatter: AnsibleOutputFormatter | None = None
        if output_callback is None:
            if context.debug:
                # In debug mode, print everything raw for troubleshooting
                def _debug_printer(text: str, end: str = ""):
                    print(text, end=end, flush=True)
                output_callback = _debug_printer
            else:
                # In normal mode, use the pretty formatter to hide Ansible noise
                formatter = AnsibleOutputFormatter()
                output_callback = formatter.process

        # Logic for Multipass Execution
        if context.use_multipass:
            # Create a temp dir for keys relative to output to keep project clean or use system temp
            temp_keys_dir = context.config.output_dir.parent / "temp_keys"
            temp_keys_dir.mkdir(parents=True, exist_ok=True)
            
            service = MultipassService(temp_keys_dir)
            
            # Context Manager ensures cleanup happens even if benchmarks fail
            with service.provision() as remote_host:
                if ui_adapter:
                    ui_adapter.show_success(f"Provisioned Multipass VM: {remote_host.address}")
                
                # Override configuration dynamically
                context.config.remote_hosts = [remote_host]
                context.config.remote_execution.enabled = True
                
                # Ensure playbook paths are absolute and valid (reset to defaults)
                # This prevents errors if the user config has broken/relative paths
                defaults = RemoteExecutionConfig()
                context.config.remote_execution.setup_playbook = defaults.setup_playbook
                context.config.remote_execution.run_playbook = defaults.run_playbook
                context.config.remote_execution.collect_playbook = defaults.collect_playbook
                
                return self._run_remote(
                    context,
                    run_id,
                    output_callback,
                    formatter,
                    ui_adapter,
                )

        if context.use_container:
            root = context.docker_workdir or context.config.output_dir.parent.parent.resolve()
            spec = ContainerRunSpec(
                tests=context.target_tests,
                cfg_path=context.config_path,
                config_path=context.config_path,
                run_id=run_id,
                remote=context.use_remote,
                image=context.docker_image,
                workdir=root,
                artifacts_dir=context.config.output_dir.resolve(),
                engine=context.docker_engine,
                build=context.docker_build,
                no_cache=context.docker_no_cache,
                debug=context.debug,
            )
            
            # Run each workload in its own container (or shared image)
            for test_name in context.target_tests:
                workload_cfg = context.config.workloads.get(test_name)
                if not workload_cfg:
                    continue
                
                try:
                    plugin = context.registry.get(workload_cfg.plugin)
                    self._container_runner.run_workload(spec, test_name, plugin)
                except Exception as e:
                    if ui_adapter:
                        ui_adapter.show_error(f"Failed to run container for {test_name}: {e}")
                    else:
                        print(f"Error running {test_name}: {e}")

            return RunResult(context=context, summary=None)

        if context.use_remote:
            return self._run_remote(
                context,
                run_id,
                output_callback,
                formatter,
                ui_adapter,
            )

        runner = LocalRunner(context.config, registry=context.registry, ui_adapter=ui_adapter)
        for test_name in context.target_tests:
            runner.run_benchmark(test_name)
        return RunResult(context=context, summary=None)

    def _run_remote(
        self,
        context: RunContext,
        run_id: Optional[str],
        output_callback: Callable[[str, str], None],
        formatter: AnsibleOutputFormatter | None,
        ui_adapter: UIAdapter | None,
    ) -> RunResult:
        """Execute a remote run using the controller with journal integration."""
        from ..controller import BenchmarkController  # Runtime import to break circular dependency

        resume_requested = context.resume_from is not None or context.resume_latest
        journal, journal_path, dashboard, effective_run_id = (
            self._prepare_journal_and_dashboard(context, run_id, ui_adapter)
        )

        # Fan-out Ansible output to both formatter and dashboard log stream.
        output_cb = output_callback
        if isinstance(dashboard, RunDashboard) and output_callback is not None:
            def _dashboard_callback(text: str, end: str = ""):
                output_callback(text, end=end)
                dashboard.add_log(text)
            output_cb = _dashboard_callback

        controller = BenchmarkController(
            context.config,
            output_callback=output_cb,
            output_formatter=formatter if not context.debug else None,
            journal_refresh=dashboard.refresh if dashboard else None,
        )

        with dashboard.live():
            summary = controller.run(
                context.target_tests,
                run_id=effective_run_id,
                journal=journal,
                resume=resume_requested,
                journal_path=journal_path,
            )

        return RunResult(context=context, summary=summary)

    def _prepare_journal_and_dashboard(
        self,
        context: RunContext,
        run_id: Optional[str],
        ui_adapter: UIAdapter | None,
    ) -> tuple[RunJournal, Path, NoopDashboard | RunDashboard, str]:
        """Load or create the run journal and optional dashboard."""
        resume_requested = context.resume_from is not None or context.resume_latest

        if resume_requested:
            if context.resume_latest:
                journal_path = self._find_latest_journal(context.config)
                if journal_path is None:
                    raise ValueError("No previous run found to resume.")
            else:
                journal_path = (
                    context.config.output_dir
                    / context.resume_from
                    / "run_journal.json"
                )
            journal = RunJournal.load(journal_path, config=context.config)
            if run_id and run_id != journal.run_id:
                raise ValueError(
                    f"Run ID mismatch: resume journal={journal.run_id}, cli={run_id}"
                )
            run_identifier = journal.run_id
        else:
            run_identifier = run_id or self._generate_run_id()
            journal_path = (
                context.config.output_dir / run_identifier / "run_journal.json"
            )
            journal = RunJournal.initialize(
                run_identifier, context.config, context.target_tests
            )

        # Persist the initial state so resume is possible even if execution aborts early
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal.save(journal_path)

        if ui_adapter and isinstance(ui_adapter, ConsoleUIAdapter):
            plan = self.get_run_plan(
                context.config,
                context.target_tests,
                docker_mode=context.use_container,
                multipass_mode=context.use_multipass,
                remote_mode=context.use_remote,
                registry=context.registry,
            )
            dashboard: NoopDashboard | RunDashboard = RunDashboard(
                ui_adapter.console, plan, journal
            )
        else:
            dashboard = NoopDashboard()

        return journal, journal_path, dashboard, run_identifier

    @staticmethod
    def _find_latest_journal(config: BenchmarkConfig) -> Path | None:
        """Return the most recent journal path if present."""
        root = config.output_dir
        if not root.exists():
            return None
        candidates = []
        for child in root.iterdir():
            candidate = child / "run_journal.json"
            if candidate.exists():
                candidates.append(candidate)
        if not candidates:
            return None
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a timestamped run id matching the controller's format."""
        return datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")
