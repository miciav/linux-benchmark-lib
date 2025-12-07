"""Application-facing run orchestration helpers for the CLI."""

from __future__ import annotations

from datetime import datetime
from collections import deque
import os
import time
import re
from dataclasses import dataclass, asdict
from contextlib import ExitStack
from typing import Callable, List, Optional, Dict, Any, TYPE_CHECKING
from pathlib import Path
import json

from lb_runner.benchmark_config import BenchmarkConfig, RemoteExecutionConfig, RemoteHostConfig
from lb_runner.events import RunEvent, LogSink
from lb_runner.local_runner import LocalRunner
from lb_runner.plugin_system.registry import PluginRegistry
from lb_runner.plugin_system.interface import WorkloadIntensity
from lb_controller.journal import RunJournal, RunStatus
from .container_service import ContainerRunner, ContainerRunSpec
from .multipass_service import MultipassService
from .setup_service import SetupService
from lb_ui.ui.console_adapter import ConsoleUIAdapter
from lb_ui.ui.run_dashboard import NoopDashboard, RunDashboard
from lb_ui.ui.types import UIAdapter

if TYPE_CHECKING:
    from ..controller import BenchmarkController, RunExecutionSummary


class AnsibleOutputFormatter:
    """Parses raw Ansible output stream and prints user-friendly status updates."""
    
    def __init__(self):
        self.task_pattern = re.compile(r"TASK \[(.*?)\]")
        self.bench_pattern = re.compile(r"Running benchmark: (.*)")
        self.current_phase = "Initializing" # Default phase
        self._always_show_tasks = (
            "workload_runner : Build repetitions list",
            "workload_runner : Run benchmark via local runner (per repetition)",
        )
    
    def set_phase(self, phase: str):
        self.current_phase = phase

    def process(self, text: str, end: str = "", log_sink: Callable[[str], None] | None = None):
        if not text:
            return
        
        lines = text.splitlines()
        for line in lines:
            self._handle_line(line, log_sink=log_sink)

    def _emit(self, message: str, log_sink: Callable[[str], None] | None) -> None:
        """Send formatted message to stdout and optional sink."""
        print(message)
        if log_sink:
            log_sink(message)

    def _handle_line(self, line: str, log_sink: Callable[[str], None] | None = None):
        line = line.strip()
        if not line:
            return

        progress = self._format_progress(line)
        if progress:
            self._emit(progress, log_sink)
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
            always = task_match.group(1).strip()
            if always in self._always_show_tasks:
                self._emit(f"• {always}", log_sink)
            else:
                self._emit(f"• [{self.current_phase}] {task_name}", log_sink)
            return

        # Format Benchmark Start (from python script)
        bench_match = self.bench_pattern.search(line)
        if bench_match:
            bench_name = bench_match.group(1)
            self._emit(f"\n>>> Benchmark: {bench_name} <<<\n", log_sink)
            return

        # Format Changes (usually means success in ansible terms)
        if line.startswith("changed:"):
            return

        # Pass through interesting lines from the benchmark script
        if "lb_runner.local_runner" in line or "Running test" in line or "Progress:" in line or "Completed" in line:
            self._emit(f"  {line}", log_sink)
            return
        
        # Pass through raw output that looks like a progress bar (rich output often has special chars)
        if "━" in line:
            self._emit(f"  {line}", log_sink)
            return

        # Pass through errors
        if "fatal:" in line or "ERROR" in line or "failed:" in line:
            self._emit(f"[!] {line}", log_sink)

    def _format_progress(self, line: str) -> str | None:
        """Render LB_EVENT progress lines into a concise message."""
        token_idx = line.find("LB_EVENT")
        if token_idx == -1:
            return None
        payload = line[token_idx + len("LB_EVENT"):].strip()
        if "{" not in payload or "}" not in payload:
            return None
        try:
            start = payload.find("{")
            end = payload.rfind("}") + 1
            data = json.loads(payload[start:end])
        except Exception:
            return None
        host = data.get("host", "?")
        workload = data.get("workload", "?")
        rep = data.get("repetition", "?")
        total = data.get("total_repetitions") or data.get("total") or "?"
        status = (data.get("status") or "").lower()
        if status == "running":
            return f"{rep}/{total} running on {host} ({workload})"
        if status == "done":
            return f"{rep}/{total} completed on {host} ({workload})"
        if status == "failed":
            return f"{rep}/{total} failed on {host} ({workload})"
        return f"{rep}/{total} {status} on {host} ({workload})"


@dataclass
class RunContext:
    """Inputs required to execute a run."""

    config: BenchmarkConfig
    target_tests: List[str]
    registry: PluginRegistry
    use_remote: bool
    use_container: bool = False
    use_multipass: bool = False
    multipass_count: int = 1
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
    journal_path: Path | None = None
    log_path: Path | None = None


class RunService:
    """Coordinate benchmark execution for CLI commands."""

    def __init__(self, registry_factory: Callable[[], PluginRegistry]):
        self._registry_factory = registry_factory
        self._container_runner = ContainerRunner()
        self._setup_service = SetupService()
        self._progress_token = "LB_EVENT"

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
        container_env = os.getenv("LB_CONTAINER_MODE", "").lower() in ("1", "true", "yes")
        container_mode = docker_mode or container_env
        
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

            if container_mode:
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

    @staticmethod
    def apply_overrides(cfg: BenchmarkConfig, intensity: str | None, debug: bool) -> None:
        """Apply CLI-driven overrides to the configuration."""
        if intensity:
            for wl_name in cfg.workloads:
                cfg.workloads[wl_name].intensity = intensity
        if debug:
            for workload in cfg.workloads.values():
                if isinstance(workload.options, dict):
                    workload.options["debug"] = True
                else:
                    try:
                        setattr(workload.options, "debug", True)
                    except Exception:
                        pass

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
        multipass_vm_count: int = 1,
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
            multipass_count=max(1, multipass_vm_count),
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

    def create_session(
        self,
        config_service: Any,
        tests: Optional[List[str]] = None,
        config_path: Optional[Path] = None,
        run_id: Optional[str] = None,
        resume: Optional[str] = None,
        remote: Optional[bool] = None,
        docker: bool = False,
        docker_image: str = "linux-benchmark-lib:dev",
        docker_engine: str = "docker",
        docker_no_build: bool = False,
        docker_no_cache: bool = False,
        repetitions: Optional[int] = None,
        multipass: bool = False,
        multipass_vm_count: int = 1,
        debug: bool = False,
        intensity: Optional[str] = None,
        ui_adapter: UIAdapter | None = None,
        setup: bool = True,
    ) -> RunContext:
        """
        Orchestrate the creation of a RunContext from raw inputs.
        
        This method consolidates configuration loading, overrides, and context building.
        """
        # 1. Load Config
        cfg, resolved, stale = config_service.load_for_read(config_path)
        if ui_adapter:
            if stale:
                ui_adapter.show_warning(f"Saved default config not found: {stale}")
            if resolved:
                ui_adapter.show_success(f"Loaded config: {resolved}")
            else:
                ui_adapter.show_warning("No config file found; using built-in defaults.")

        # 2. Overrides
        # Force setup flag from CLI onto the config, which drives logic in execute()
        cfg.remote_execution.run_setup = setup
        if not setup:
            cfg.remote_execution.run_teardown = False
        
        if repetitions is not None:
            cfg.repetitions = repetitions
            if ui_adapter:
                ui_adapter.show_info(f"Using {repetitions} repetitions for this run")

        self.apply_overrides(cfg, intensity=intensity, debug=debug)
        if intensity and ui_adapter:
            ui_adapter.show_info(f"Global intensity override: {intensity}")
            
        cfg.ensure_output_dirs()
        
        # 3. Target Tests
        target_tests = tests or [name for name, wl in cfg.workloads.items() if wl.enabled]
        if not target_tests:
            raise ValueError("No workloads selected to run.")

        # 4. Build Context
        context = self.build_context(
            cfg,
            target_tests,
            remote_override=remote,
            docker=docker,
            multipass=multipass,
            docker_image=docker_image,
            docker_engine=docker_engine,
            docker_build=not docker_no_build,
            docker_no_cache=docker_no_cache,
            config_path=resolved,
            debug=debug,
            resume=resume,
            multipass_vm_count=multipass_vm_count,
        )
        return context

    def execute(
        self,
        context: RunContext,
        run_id: Optional[str],
        output_callback: Optional[Callable[[str, str], None]] = None,
        ui_adapter: UIAdapter | None = None,
    ) -> RunResult:
        """Execute benchmarks using the provided context."""
        # Shared journal/log setup for all modes (local, container, remote)
        journal: RunJournal | None = None
        journal_path: Path | None = None
        log_path: Path | None = None
        run_identifier = run_id
        dashboard: NoopDashboard | RunDashboard | None = None
        
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
            
            count = max(1, context.multipass_count)

            # Context Manager ensures cleanup happens even if benchmarks fail
            with ExitStack() as stack:
                remote_hosts: list[RemoteHostConfig] = []
                for _ in range(count):
                    service = MultipassService(temp_keys_dir)
                    remote_host = stack.enter_context(service.provision())
                    remote_hosts.append(remote_host)
                    if ui_adapter:
                        ui_adapter.show_success(f"Provisioned Multipass VM: {remote_host.address}")
                
                # Override configuration dynamically
                context.config.remote_hosts = remote_hosts
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
            journal, journal_path, dashboard, run_identifier = self._prepare_journal_and_dashboard(
                context, run_id, ui_adapter
            )
            log_path = journal_path.parent / "run.log"
            # Ensure directory exists
            journal_path.parent.mkdir(parents=True, exist_ok=True)

            root = context.docker_workdir or context.config.output_dir.parent.resolve()
            spec = ContainerRunSpec(
                tests=context.target_tests,
                cfg_path=context.config_path,
                config_path=context.config_path,
                run_id=run_identifier,
                remote=context.use_remote,
                image=context.docker_image,
                workdir=root,
                artifacts_dir=context.config.output_dir.resolve(),
                engine=context.docker_engine,
                build=context.docker_build,
                no_cache=context.docker_no_cache,
                debug=context.debug,
                repetitions=context.config.repetitions,
            )
            
            def _container_output_handler(line: str) -> None:
                # 1. Parse Event for UI updates (In-Memory Only)
                # We do NOT save to disk here to avoid race conditions with the inner process
                # which has the volume mounted and writes the authoritative journal.
                info = self._parse_progress_line(line)
                if info:
                    status_map = {
                        "running": RunStatus.RUNNING,
                        "done": RunStatus.COMPLETED,
                        "failed": RunStatus.FAILED,
                    }
                    journal.update_task(
                        info["host"],
                        info["workload"],
                        info["rep"],
                        status_map.get(info["status"].lower(), RunStatus.RUNNING),
                        action="container_run",
                    )
                    if isinstance(dashboard, RunDashboard):
                        dashboard.refresh()
                    return  # Do not log event protocol lines to the UI

                # 2. Filter and Log to Dashboard
                stripped = line.strip()
                if not stripped:
                    return

                # Suppress progress bar updates from HeadlessUIAdapter
                # Format: "workload (rep N): X%"
                if "(rep " in stripped and stripped.endswith("%"):
                    return

                if isinstance(dashboard, RunDashboard):
                    # Only show relevant logs, filter out likely internal noise if needed
                    dashboard.add_log(line.rstrip())
                else:
                    print(line, end="")

            with dashboard.live():
                for test_name in context.target_tests:
                    workload_cfg = context.config.workloads.get(test_name)
                    if not workload_cfg:
                        continue
                    
                    try:
                        plugin = context.registry.get(workload_cfg.plugin)
                        self._container_runner.run_workload(
                            spec,
                            test_name,
                            plugin,
                            ui_adapter=ui_adapter,
                            output_callback=_container_output_handler,
                        )
                        
                        # Reload journal from disk to ensure we have the authoritative state
                        # (e.g. COMPLETED status) written by the inner process.
                        if journal_path.exists():
                            try:
                                disk_journal = RunJournal.load(journal_path)
                                journal.tasks = disk_journal.tasks
                            except Exception:
                                pass

                        if isinstance(dashboard, RunDashboard):
                            dashboard.refresh()

                    except Exception as e:
                        if ui_adapter:
                            ui_adapter.show_error(f"Failed to run container for {test_name}: {e}")
                        else:
                            print(f"Error running {test_name}: {e}")
                        
                        # Fail all reps for this workload
                        for rep in range(1, context.config.repetitions + 1):
                            h_name = context.config.remote_hosts[0].name if context.config.remote_hosts else "localhost"
                            journal.update_task(
                                h_name,
                                test_name,
                                rep,
                                RunStatus.FAILED,
                                action="container_run",
                                error=str(e),
                            )
                        journal.save(journal_path)

            return RunResult(context=context, summary=None, journal_path=journal_path, log_path=log_path)

        if context.use_remote:
            return self._run_remote(
                context,
                run_id,
                output_callback,
                formatter,
                ui_adapter,
            )

        # --- LOCAL EXECUTION WITH 2-LEVEL SETUP ---
        journal, journal_path, dashboard, run_identifier = self._prepare_journal_and_dashboard(
            context, run_id, ui_adapter
        )
        log_path = journal_path.parent / "run.log"
        log_file = log_path.open("a", encoding="utf-8")
        def _progress_cb(event: RunEvent) -> None:
            status_map = {
                "running": RunStatus.RUNNING,
                "done": RunStatus.COMPLETED,
                "failed": RunStatus.FAILED,
            }
            mapped = status_map.get(event.status.lower(), RunStatus.RUNNING)
            journal.update_task(event.host, event.workload, event.repetition, mapped, action="local_run")
            journal.save(journal_path)
            if isinstance(dashboard, RunDashboard):
                dashboard.refresh()

        runner = LocalRunner(
            context.config,
            registry=context.registry,
            ui_adapter=ui_adapter,
            progress_callback=_progress_cb,
            host_name=(context.config.remote_hosts[0].name if context.config.remote_hosts else "localhost"),
        )
        
        # Level 1: Global Setup
        if context.config.remote_execution.run_setup:
            if ui_adapter:
                ui_adapter.show_info("Running global setup (local)...")
            if not self._setup_service.provision_global():
                msg = "Global setup failed (local)."
                if ui_adapter:
                    ui_adapter.show_error(msg)
                print(msg)
                log_file.write(msg + "\n")
                log_file.close()
                journal.save(journal_path)
                if isinstance(dashboard, RunDashboard):
                    dashboard.refresh()
                return RunResult(context=context, summary=None, journal_path=journal_path, log_path=log_path)

        try:
            for test_name in context.target_tests:
                workload_cfg = context.config.workloads.get(test_name)
                if not workload_cfg:
                    continue

                # Get plugin from registry (cache check already done by builder)
                try:
                    plugin = context.registry.get(workload_cfg.plugin)
                except Exception as e:
                    if ui_adapter:
                        ui_adapter.show_error(f"Skipping {test_name}: {e}")
                    log_file.write(f"Skipping {test_name}: {e}\n")
                    log_file.flush()
                    continue

                # Level 2: Workload Setup
                if context.config.remote_execution.run_setup:
                    if ui_adapter:
                        ui_adapter.show_info(f"Running setup for {test_name} (local)...")
                    
                    if not self._setup_service.provision_workload(plugin):
                        msg = f"Setup failed for {test_name} (local). Skipping."
                        if ui_adapter:
                            ui_adapter.show_error(msg)
                        print(msg)
                        log_file.write(msg + "\n")
                        log_file.flush()
                        
                        # Cleanup attempt if setup failed? Usually setup is idempotent or fail-fast.
                        # We try teardown just in case.
                        if context.config.remote_execution.run_teardown:
                            self._setup_service.teardown_workload(plugin)
                        continue

                host_name = (context.config.remote_hosts[0].name
                             if context.config.remote_hosts else "localhost")
                try:
                    # EXECUTION LOOP (LocalRunner handles repetitions)
                    success = runner.run_benchmark(test_name, run_id=run_identifier)
                    if success:
                        log_file.write(f"{test_name} completed locally\n")
                    else:
                        log_file.write(f"{test_name} failed locally\n")
                    log_file.flush()
                    journal.save(journal_path)
                except Exception as e:
                    for rep in range(1, context.config.repetitions + 1):
                        journal.update_task(
                            host_name,
                            test_name,
                            rep,
                            RunStatus.FAILED,
                            action="local_run",
                            error=str(e),
                        )
                    journal.save(journal_path)
                    log_file.write(f"{test_name} failed locally: {e}\n")
                    log_file.flush()
                    if ui_adapter:
                        ui_adapter.show_error(f"{test_name} failed locally: {e}")
                finally:
                    # Level 2: Workload Teardown
                    if context.config.remote_execution.run_teardown:
                        if ui_adapter:
                            ui_adapter.show_info(f"Running teardown for {test_name} (local)...")
                        self._setup_service.teardown_workload(plugin)
        
        finally:
            # Level 1: Global Teardown
            if context.config.remote_execution.run_teardown:
                if ui_adapter:
                    ui_adapter.show_info("Running global teardown (local)...")
                self._setup_service.teardown_global()

        log_file.close()
        if isinstance(dashboard, RunDashboard):
            dashboard.refresh()
        return RunResult(context=context, summary=None, journal_path=journal_path, log_path=log_path)

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
        log_path = journal_path.parent / "run.log"

        # Fan-out Ansible output to both formatter and dashboard log stream.
        output_cb = output_callback
        if isinstance(dashboard, RunDashboard) and output_callback is not None:
            last_refresh = 0.0
            def _dashboard_callback(text: str, end: str = ""):
                nonlocal last_refresh
                # If we're using the pretty formatter, let it drive both stdout and dashboard.
                if formatter and output_callback == formatter.process:
                    formatter.process(text, end=end, log_sink=dashboard.add_log)
                else:
                    output_callback(text, end=end)
                    dashboard.add_log(text)
                now = time.monotonic()
                if now - last_refresh > 0.25:
                    dashboard.refresh()
                    last_refresh = now
            output_cb = _dashboard_callback

        # Tee streamed output to a log file to aid troubleshooting after the run.
        log_file = log_path.open("a", encoding="utf-8")
        downstream = output_cb

        sink = LogSink(journal, journal_path, log_path)
        recent_events: deque[tuple[str, str, int, str]] = deque()
        dedupe_limit = 200
        recent_set: set[tuple[str, str, int, str]] = set()

        def _ingest_event(event: RunEvent, source: str = "unknown") -> None:
            key = (event.host, event.workload, event.repetition, event.status)
            if key in recent_set:
                return
            recent_events.append(key)
            recent_set.add(key)
            # Keep the dedupe window bounded
            if len(recent_events) > dedupe_limit:
                old = recent_events.popleft()
                if old in recent_set:
                    recent_set.remove(old)

            sink.emit(event)
            if isinstance(dashboard, RunDashboard):
                dashboard.mark_event(source)
                dashboard.add_log(
                    f"• {event.repetition}/{event.total_repetitions} {event.status} on {event.host} ({event.workload})"
                )
                dashboard.refresh()

        def _handle_progress(line: str) -> None:
            info = self._parse_progress_line(line)
            if not info:
                return
            try:
                event = RunEvent(
                    run_id=journal.run_id,
                    host=info["host"],
                    workload=info["workload"],
                    repetition=info["rep"],
                    total_repetitions=info.get("total", context.config.repetitions),
                    status=info["status"],
                    message=info.get("message") or "",
                    timestamp=time.time(),
                )
                _ingest_event(event, source="stdout")
            except Exception:
                pass

        def _tee_output(text: str, end: str = "") -> None:
            fragment = text + (end if end else "\n")
            # Log everything for post-mortem debugging.
            try:
                log_file.write(fragment)
                log_file.flush()
            except Exception:
                pass
            for line in fragment.splitlines():
                _handle_progress(line)
            if downstream:
                downstream(text, end=end)

        output_cb = _tee_output

        controller = BenchmarkController(
            context.config,
            output_callback=output_cb,
            output_formatter=formatter if not context.debug else None,
            journal_refresh=dashboard.refresh if dashboard else None,
        )
        elapsed: float | None = None
        try:
            with dashboard.live():
                start_ts = time.monotonic()
                summary = controller.run(
                    context.target_tests,
                    run_id=effective_run_id,
                    journal=journal,
                    resume=resume_requested,
                    journal_path=journal_path,
                )
                elapsed = time.monotonic() - start_ts
                msg = f"Run {effective_run_id} completed in {elapsed:.1f}s"
                try:
                    log_file.write(msg + "\n")
                    log_file.flush()
                except Exception:
                    pass
                if ui_adapter:
                    ui_adapter.show_info(msg)
                else:
                    print(msg)
        finally:
            log_file.close()

        if isinstance(dashboard, RunDashboard):
            dashboard.refresh()

        sink.close()
        return RunResult(
            context=context,
            summary=summary,
            journal_path=journal_path,
            log_path=log_path,
        )

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

    def _build_journal_from_results(
        self,
        run_id: str,
        context: RunContext,
        host_name: str,
    ) -> RunJournal:
        """
        Construct a RunJournal from existing *_results.json artifacts when a journal is missing.
        """
        journal = RunJournal.initialize(run_id, context.config, context.target_tests)
        output_root = context.config.output_dir / run_id
        for test_name in context.target_tests:
            results_file = output_root / f"{test_name}_results.json"
            if not results_file.exists():
                continue
            try:
                entries = json.loads(results_file.read_text())
            except Exception:
                continue
            for entry in entries or []:
                rep = entry.get("repetition")
                if rep is None:
                    continue
                task = journal.get_task(host_name, test_name, rep)
                if not task:
                    continue
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
                gen_result = entry.get("generator_result") or {}
                gen_error = gen_result.get("error")
                gen_rc = gen_result.get("returncode")
                if gen_error or (gen_rc not in (None, 0)):
                    journal.update_task(
                        host_name,
                        test_name,
                        rep,
                        RunStatus.FAILED,
                        action="container_run",
                        error=gen_error or f"returncode={gen_rc}",
                    )
                else:
                    journal.update_task(
                        host_name,
                        test_name,
                        rep,
                        RunStatus.COMPLETED,
                        action="container_run",
                    )
        return journal

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

    def _parse_progress_line(self, line: str) -> dict[str, Any] | None:
        """Parse progress markers emitted by LocalRunner."""
        line = line.strip()
        token_idx = line.find(self._progress_token)
        if token_idx == -1:
            return None
        payload = line[token_idx + len(self._progress_token):].strip()
        # Try to extract a JSON object even if wrapped inside other text.
        if "{" in payload and "}" in payload:
            start = payload.find("{")
            end = payload.rfind("}") + 1
            candidate = payload[start:end]
            for attempt in (candidate, candidate.replace(r"\"", '"')):
                try:
                    data = json.loads(attempt)
                    break
                except Exception:
                    data = None
            if not data:
                return None
            required = {"host", "workload", "repetition", "status"}
            if not required.issubset(data.keys()):
                return None
            return {
                "host": data["host"],
                "workload": data["workload"],
                "rep": data.get("repetition", 0),
                "status": data["status"],
                "total": data.get("total_repetitions", 0),
                "message": data.get("message"),
            }
        return None
