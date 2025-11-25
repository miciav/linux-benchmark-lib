"""Application-facing run orchestration helpers for the CLI."""

from __future__ import annotations

import ctypes.util
from dataclasses import dataclass
from typing import Callable, List, Optional, Dict, Any
from pathlib import Path

from benchmark_config import BenchmarkConfig
from controller import BenchmarkController, RunExecutionSummary
from local_runner import LocalRunner
from plugins.registry import PluginRegistry
from services.container_service import ContainerRunner, ContainerRunSpec
from ui.types import UIAdapter


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
        
        Returns a list of dictionaries containing status, duration, etc.
        """
        registry = registry or self._registry_factory()
        plan = []
        
        for name in tests:
            wl = cfg.workloads.get(name)
            item = {
                "name": name,
                "plugin": wl.plugin if wl else "unknown",
                "status": "[yellow]?[/yellow]",
                "duration": f"{cfg.test_duration_seconds}s",
                "warmup_cooldown": f"{cfg.warmup_seconds}s/{cfg.cooldown_seconds}s",
                "repetitions": str(cfg.repetitions),
            }
            
            if not wl:
                item["status"] = "[yellow]?[/yellow]"
                plan.append(item)
                continue

            try:
                plugin = registry.get(wl.plugin)
            except Exception:
                item["status"] = "[red]✗[/red]"
                plan.append(item)
                continue

            if docker_mode:
                item["status"] = "[green]Container[/green]"
                plan.append(item)
                continue

            # Special-case iperf3 to avoid noisy client creation
            if plugin.name == "iperf3":
                lib = ctypes.util.find_library("iperf")
                item["status"] = "[green]✓[/green]" if lib else "[red]✗[/red]"
                plan.append(item)
                continue

            try:
                gen = plugin.create_generator(wl.options)
                # Use public API for checking prerequisites if available
                checker = getattr(gen, "check_prerequisites", None)
                if callable(checker):
                    is_ok = checker()
                else:
                    # Fallback to legacy private method
                    validator = getattr(gen, "_validate_environment", None)
                    is_ok = validator() if callable(validator) else False
                
                item["status"] = "[green]✓[/green]" if is_ok else "[red]✗[/red]"
            except Exception:
                item["status"] = "[red]✗[/red]"
            
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
        project_root = Path(__file__).resolve().parent.parent
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
            self._container_runner.run(spec)
            return RunResult(context=context, summary=None)

        if context.use_remote:
            controller = BenchmarkController(context.config, output_callback=output_callback)
            summary = controller.run(context.target_tests, run_id=run_id)
            return RunResult(context=context, summary=summary)

        runner = LocalRunner(context.config, registry=context.registry, ui_adapter=ui_adapter)
        for test_name in context.target_tests:
            runner.run_benchmark(test_name)
        return RunResult(context=context, summary=None)
