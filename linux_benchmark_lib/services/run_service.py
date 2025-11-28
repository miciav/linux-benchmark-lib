"""Application-facing run orchestration helpers for the CLI."""

from __future__ import annotations

import ctypes.util
from dataclasses import dataclass, asdict
from typing import Callable, List, Optional, Dict, Any, TYPE_CHECKING
from pathlib import Path

from ..benchmark_config import BenchmarkConfig
from ..local_runner import LocalRunner
from ..plugins.registry import PluginRegistry
from ..plugins.interface import WorkloadIntensity
from .container_service import ContainerRunner, ContainerRunSpec
from ..ui.types import UIAdapter

if TYPE_CHECKING:
    from ..controller import BenchmarkController, RunExecutionSummary


@dataclass
class RunContext:
    """Inputs required to execute a run."""

    config: BenchmarkConfig
    target_tests: List[str]
    registry: PluginRegistry
    use_remote: bool
    use_container: bool = False
    config_path: Optional[Path] = None
    docker_image: str = "linux-benchmark-lib:dev"
    docker_engine: str = "docker"
    docker_build: bool = True
    docker_no_cache: bool = False
    docker_workdir: Path | None = None


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
        docker_image: str = "linux-benchmark-lib:dev",
        docker_engine: str = "docker",
        docker_build: bool = True,
        docker_no_cache: bool = False,
        config_path: Optional[Path] = None,
    ) -> RunContext:
        """Compute the run context and registry."""
        registry = self._registry_factory()
        target_tests = tests or [
            name for name, workload in cfg.workloads.items() if workload.enabled
        ]
        use_remote = remote_override if remote_override is not None else cfg.remote_execution.enabled

        # Use repo root (where Dockerfile lives) as the container build context
        project_root = Path(__file__).resolve().parent.parent.parent
        return RunContext(
            config=cfg,
            target_tests=target_tests,
            registry=registry,
            use_remote=use_remote,
            use_container=docker,
            config_path=config_path,
            docker_image=docker_image,
            docker_engine=docker_engine,
            docker_build=docker_build,
            docker_no_cache=docker_no_cache,
            docker_workdir=project_root if docker else None,
        )

    def execute(
        self,
        context: RunContext,
        run_id: Optional[str],
        output_callback: Optional[Callable[[str, str], None]] = None,
        ui_adapter: UIAdapter | None = None,
    ) -> RunResult:
        """Execute benchmarks using the provided context."""
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
            from ..controller import BenchmarkController  # Runtime import to break circular dependency
            controller = BenchmarkController(context.config, output_callback=output_callback)
            summary = controller.run(context.target_tests, run_id=run_id)
            return RunResult(context=context, summary=summary)

        runner = LocalRunner(context.config, registry=context.registry, ui_adapter=ui_adapter)
        for test_name in context.target_tests:
            runner.run_benchmark(test_name)
        return RunResult(context=context, summary=None)
