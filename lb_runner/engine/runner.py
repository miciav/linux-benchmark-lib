"""
Local controller module for managing the benchmark process.

This module coordinates the execution of workload generators and metric collectors,
managing the overall benchmark workflow.
"""

from __future__ import annotations

import os
import logging
import platform
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from lb_common.errors import LBError, error_to_payload
from lb_runner.models.config import BenchmarkConfig, WorkloadConfig
from lb_runner.models.events import RunEvent
from lb_runner.services.runner_log_manager import RunnerLogManager
from lb_runner.services.runner_output_manager import RunnerOutputManager
from lb_plugins.api import BaseGenerator, PluginRegistry, WorkloadPlugin
from lb_runner.metric_collectors.builtin import builtin_collectors
from lb_runner.metric_collectors.registry import CollectorRegistry
from lb_runner.registry import RunnerRegistry
from lb_runner.engine.execution import StopRequested
from lb_runner.engine.executor import RepetitionExecutor
from lb_runner.engine.context import RunnerContext
from lb_runner.engine.progress import RunProgressEmitter
from lb_runner.engine.planning import RunPlanner
from lb_runner.engine.run_scope import RunScopeManager
from lb_runner.services.result_persister import ResultPersister
from lb_runner.services.results import build_rep_result
from lb_runner.engine.stop_context import should_stop, stop_context
from lb_runner.engine.stop_token import StopToken
from lb_runner.engine.metrics import MetricManager
logger = logging.getLogger(__name__)


class LocalRunner:
    """Local agent for executing benchmarks on a single node."""
    
    def __init__(
        self,
        config: BenchmarkConfig,
        registry: PluginRegistry | RunnerRegistry,
        progress_callback: Optional[Callable[[RunEvent], None]] = None,
        host_name: str | None = None,
        stop_token: StopToken | None = None,
        collector_registry: CollectorRegistry | None = None,
    ):
        """
        Initialize the local runner.
        
        Args:
            config: Benchmark configuration
        """
        self.config = config
        self.test_results: List[Dict[str, Any]] = []
        self.plugin_registry = self._resolve_registry(registry, collector_registry)
        workloads = getattr(self.config, "workloads", {})
        repetitions = getattr(self.config, "repetitions", 1)
        plugin_settings = getattr(self.config, "plugin_settings", {})
        self._planner = RunPlanner(
            workloads=workloads,
            repetitions=repetitions,
            logger=logger,
            plugin_settings=plugin_settings,
        )
        self._scope_manager = RunScopeManager(self.config, logger)
        self._result_persister = ResultPersister()
        self._current_run_id: Optional[str] = None
        self._host_name = host_name or os.environ.get("LB_RUN_HOST") or platform.node() or "localhost"
        self._progress = RunProgressEmitter(host=self._host_name, callback=progress_callback)
        self._stop_token = stop_token
        self._output_manager = RunnerOutputManager(
            config=self.config,
            persister=self._result_persister,
            logger=logger,
        )
        self._log_manager = RunnerLogManager(
            config=self.config,
            host_name=self._host_name,
            logger=logger,
        )
        self._metric_manager = MetricManager(
            registry=self.plugin_registry,
            output_manager=self._output_manager,
            host_name=self._host_name,
        )

    @property
    def system_info(self) -> Optional[Dict[str, Any]]:
        return self._metric_manager.system_info

    @staticmethod
    def _resolve_registry(
        registry: PluginRegistry | RunnerRegistry,
        collector_registry: CollectorRegistry | None,
    ) -> RunnerRegistry | Any:
        if hasattr(registry, "create_collectors") and hasattr(registry, "create_generator"):
            return registry
        collectors = collector_registry or CollectorRegistry(builtin_collectors())
        return RunnerRegistry(registry, collectors)
        
    def collect_system_info(self) -> Dict[str, Any]:
        """
        Collect detailed information about the system.
        
        Returns:
            Dictionary containing system information
        """
        return self._metric_manager.collect_system_info()

    def _workload_output_dir(self, workload: str) -> Path:
        """
        Return the workload-scoped output directory for the current run.

        Ensures the directory exists so collectors and plugins can write into it.
        """
        return self._output_manager.workload_output_dir(workload)

    def run_benchmark(
        self,
        test_type: str,
        repetition_override: int | None = None,
        total_repetitions: int | None = None,
        run_id: str | None = None,
        pending_reps: List[int] | None = None,
    ) -> bool:
        """
        Run a complete benchmark test.
        
        Args:
            test_type: Name of the workload to run (plugin id)
            repetition_override: When set, run only this repetition index.
            total_repetitions: Total repetitions planned (for display purposes).
        """
        with stop_context(self._stop_token):
            total_reps = total_repetitions or self.config.repetitions
            reps = self._planner.select_repetitions(repetition_override, pending_reps)
            first_rep = reps[0] if reps else 1

            self._prepare_run_scope(
                run_id,
                workload=test_type,
                repetition=first_rep,
                phase="setup",
            )
            logger.info(f"Starting benchmark: {test_type}")

            if self.config.collect_system_info and not self.system_info:
                self.collect_system_info()

            workload_cfg = self._planner.resolve_workload(test_type)
            plugin: WorkloadPlugin = self.plugin_registry.get(workload_cfg.plugin)

            success_overall = True
            for idx, rep in enumerate(reps):
                success = self._run_single_repetition(
                    test_type=test_type,
                    workload_cfg=workload_cfg,
                    plugin=plugin,
                    repetition=rep,
                    total_reps=total_reps,
                )
                success_overall = success_overall and success

                if idx < len(reps) - 1 and self.config.cooldown_seconds > 0:
                    logger.info("Cooldown period: %s seconds", self.config.cooldown_seconds)
                    time.sleep(self.config.cooldown_seconds)

                if should_stop(self._stop_token):
                    break

            logger.info(f"Completed benchmark: {test_type}")
            return success_overall

    def _prepare_run_scope(
        self,
        run_id: str | None,
        workload: str | None = None,
        repetition: int | None = None,
        phase: str | None = None,
    ) -> None:
        scope = self._scope_manager.prepare(run_id)
        self._current_run_id = scope.run_id
        self._progress.set_run_id(scope.run_id)
        self._output_manager.set_scope(
            scope.run_id,
            scope.output_root,
            scope.data_export_root,
        )
        self._log_manager.sync_loki_env()
        if scope.output_root:
            self._log_manager.attach(
                output_dir=scope.output_root,
                run_id=scope.run_id,
                workload=workload,
                repetition=repetition,
                phase=phase,
            )

    def _run_single_repetition(
        self,
        test_type: str,
        workload_cfg: WorkloadConfig,
        plugin: WorkloadPlugin,
        repetition: int,
        total_reps: int,
    ) -> bool:
        self._set_log_phase(
            "setup",
            workload=test_type,
            repetition=repetition,
        )
        if should_stop(self._stop_token):
            logger.info("Stop requested; aborting remaining repetitions.")
            self._emit_progress(test_type, repetition, total_reps, "stopped")
            return False

        logger.info("Starting repetition %s/%s", repetition, total_reps)
        config_input = self._planner.resolve_config_input(workload_cfg, plugin)
        
        context = RunnerContext(
            run_id=self._current_run_id,
            config=self.config,
            output_manager=self._output_manager,
            log_manager=self._log_manager,
            metric_manager=self._metric_manager,
            stop_token=self._stop_token,
            host_name=self._host_name,
        )

        executor = RepetitionExecutor(context)

        generator: Any | None = None
        try:
            generator = self.plugin_registry.create_generator(
                workload_cfg.plugin, config_input
            )
            self._emit_progress(test_type, repetition, total_reps, "running")
            
            result = executor.execute(
                test_name=test_type,
                generator=generator,
                repetition=repetition,
                total_repetitions=total_reps,
            )
            
            if isinstance(generator, BaseGenerator):
                self._cleanup_generator(generator, test_type, repetition)
            self._process_results(test_type, [result], plugin=plugin)
            
            success = bool(result.get("success", True))
            error_message = "" if success else str(result.get("error") or "")
            error_type = result.get("error_type") if not success else None
            error_context = result.get("error_context") if not success else None
            self._emit_progress(
                test_type, 
                repetition, 
                total_reps, 
                "done" if success else "failed",
                message=error_message,
                error_type=error_type,
                error_context=error_context,
            )
            return success
        except StopRequested:
            logger.info("Benchmark interrupted.")
            self._emit_progress(test_type, repetition, total_reps, "stopped")
            return False
        except LBError as exc:
            logger.exception(
                "Workload '%s' failed on repetition %s", test_type, repetition
            )
            error_payload = error_to_payload(exc)
            workload_dir = self._workload_output_dir(test_type)
            rep_dir = workload_dir / f"rep{repetition}"
            rep_dir.mkdir(parents=True, exist_ok=True)
            generator_result: Any = {}
            if generator is not None and hasattr(generator, "get_result"):
                try:
                    generator_result = generator.get_result()
                except Exception:
                    logger.debug("Failed to read generator result after error", exc_info=True)
            result = build_rep_result(
                test_name=test_type,
                repetition=repetition,
                rep_dir=rep_dir,
                generator_result=generator_result,
                test_start_time=None,
                test_end_time=None,
            )
            result.update(error_payload)
            result["success"] = False
            if isinstance(generator, BaseGenerator):
                self._cleanup_generator(generator, test_type, repetition)
            try:
                self._output_manager.persist_rep_result(rep_dir, result)
                self._process_results(test_type, [result], plugin=plugin)
            except Exception:
                logger.exception(
                    "Failed to persist failure result for %s rep %s",
                    test_type,
                    repetition,
                )
            self._emit_progress(
                test_type,
                repetition,
                total_reps,
                "failed",
                message=error_payload.get("error", ""),
                error_type=error_payload.get("error_type"),
                error_context=error_payload.get("error_context"),
            )
            return False
        except Exception:
            logger.exception(
                "Unexpected failure running workload '%s' rep %s", test_type, repetition
            )
            raise

    def _cleanup_generator(
        self, generator: BaseGenerator, test_type: str, repetition: int
    ) -> None:
        try:
            generator.cleanup()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.warning(
                "Generator cleanup failed for %s rep %s: %s", test_type, repetition, exc
            )
    
    def _process_results(
        self,
        test_name: str,
        results: List[Dict[str, Any]],
        plugin: WorkloadPlugin | None = None,
    ) -> None:
        """Process and save test results."""
        target_root = self._workload_output_dir(test_name)
        self._output_manager.process_results(
            plugin=plugin,
            results=results,
            target_root=target_root,
            test_name=test_name,
        )

    def _emit_progress(
        self,
        test_name: str,
        repetition: int,
        total_repetitions: int,
        status: str,
        message: str = "",
        *,
        error_type: str | None = None,
        error_context: dict[str, Any] | None = None,
    ) -> None:
        """Notify progress callback and stdout marker for remote parsing."""
        self._progress.emit(
            test_name,
            repetition,
            total_repetitions,
            status,
            message=message,
            error_type=error_type,
            error_context=error_context,
        )

    def run_all_benchmarks(self) -> None:
        """Run all configured benchmark tests."""
        run_id = self._planner.generate_run_id()
        for test_name, workload in self.config.workloads.items():
            if not workload.enabled:
                logger.info("Skipping disabled workload: %s", test_name)
                continue
            try:
                self.run_benchmark(test_name, run_id=run_id)
            except Exception:
                logger.exception("Failed to run %s benchmark", test_name)

    def _set_log_phase(
        self,
        phase: str | None,
        *,
        workload: str,
        repetition: int,
    ) -> None:
        if not self._current_run_id:
            return
        output_dir = self._output_manager.output_root() or self.config.output_dir
        self._log_manager.attach(
            output_dir=output_dir,
            run_id=self._current_run_id,
            workload=workload,
            repetition=repetition,
            phase=phase,
        )
