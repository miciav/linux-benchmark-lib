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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from lb_runner.models.config import BenchmarkConfig, WorkloadConfig
from lb_runner.services.log_handler import LBEventLogHandler
from lb_runner.services.storage import (
    workload_output_dir,
    write_system_info_artifacts,
)
from lb_plugins.api import BaseGenerator, PluginRegistry, WorkloadPlugin
from lb_runner.metric_collectors.builtin import builtin_collectors
from lb_runner.metric_collectors.registry import CollectorRegistry
from lb_runner.registry import RunnerRegistry
from lb_runner.engine.execution import (
    StopRequested,
    generator_running,
    pre_test_cleanup,
    prepare_generator,
    resolve_duration,
    wait_for_generator,
)
from lb_runner.engine.progress import RunProgressEmitter
from lb_runner.engine.planning import RunPlanner
from lb_runner.engine.run_scope import RunScopeManager
from lb_runner.services.collector_coordinator import CollectorCoordinator
from lb_runner.services.result_persister import ResultPersister
from lb_runner.services.results import build_rep_result
from lb_runner.engine.stop_token import StopToken
from lb_runner.services import system_info
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
        self.system_info: Optional[Dict[str, Any]] = None
        self.test_results: List[Dict[str, Any]] = []
        self.plugin_registry = self._resolve_registry(registry, collector_registry)
        workloads = getattr(self.config, "workloads", {})
        repetitions = getattr(self.config, "repetitions", 1)
        self._planner = RunPlanner(
            workloads=workloads,
            repetitions=repetitions,
            logger=logger,
        )
        self._scope_manager = RunScopeManager(self.config, logger)
        self._collector_coordinator = CollectorCoordinator(self.plugin_registry)
        self._result_persister = ResultPersister()
        self._current_run_id: Optional[str] = None
        self._output_root: Optional[Path] = None
        self._data_export_root: Optional[Path] = None
        self._host_name = host_name or os.environ.get("LB_RUN_HOST") or platform.node() or "localhost"
        self._progress = RunProgressEmitter(host=self._host_name, callback=progress_callback)
        self._stop_token = stop_token

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
        logger.info("Collecting system information")

        collected = system_info.collect_system_info()
        self.system_info = collected.to_dict()

        # Persist JSON/CSV alongside run outputs when available
        if self._output_root:
            write_system_info_artifacts(collected, self._output_root, logger)

        return self.system_info

    def _workload_output_dir(self, workload: str) -> Path:
        """
        Return the workload-scoped output directory for the current run.

        Ensures the directory exists so collectors and plugins can write into it.
        """
        base = self._output_root or self.config.output_dir
        path = workload_output_dir(base, workload, ensure=True)
        return path

    def _run_single_test(
        self,
        test_name: str,
        generator: Any,
        repetition: int,
        total_repetitions: int,
        stop_token: StopToken | None = None,
    ) -> Dict[str, Any]:
        """
        Run a single test with the specified generator.
        
        Args:
            test_name: Name of the test
            generator: Workload generator instance
            repetition: Repetition number
            
        Returns:
            Dictionary containing test results
        """
        logger.info(f"Running test '{test_name}' - Repetition {repetition}")
        workload_dir, rep_dir = self._prepare_workload_dirs(test_name, repetition)
        collectors = self._collector_coordinator.create_collectors(self.config)
        duration = self._resolve_duration(generator)
        log_handler = self._attach_event_logger(
            test_name, repetition, total_repetitions
        )

        test_start_time, test_end_time = self._execute_generator(
            generator,
            collectors,
            duration,
            test_name,
            repetition,
            stop_token=stop_token,
        )

        if log_handler:
            logging.getLogger().removeHandler(log_handler)

        result = self._finalize_single_test(
            generator,
            collectors,
            workload_dir,
            rep_dir,
            test_name,
            repetition,
            total_repetitions,
            test_start_time,
            test_end_time,
        )

        return result

    def _prepare_workload_dirs(self, test_name: str, repetition: int) -> tuple[Path, Path]:
        workload_dir = self._workload_output_dir(test_name)
        rep_dir = workload_dir / f"rep{repetition}"
        rep_dir.mkdir(parents=True, exist_ok=True)
        return workload_dir, rep_dir

    def _resolve_duration(self, generator: Any) -> int:
        return resolve_duration(self.config, generator, logger)

    def _attach_event_logger(
        self, test_name: str, repetition: int, total_repetitions: int
    ) -> logging.Handler | None:
        if os.environ.get("LB_ENABLE_EVENT_LOGGING") != "1":
            return None
        handler = LBEventLogHandler(
            run_id=self._current_run_id or "",
            host=self._host_name,
            workload=test_name,
            repetition=repetition,
            total_repetitions=total_repetitions,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)
        return handler

    def _execute_generator(
        self,
        generator: Any,
        collectors: list[Any],
        duration: int,
        test_name: str,
        repetition: int,
        stop_token: StopToken | None = None,
    ) -> tuple[datetime | None, datetime | None]:
        self._pre_test_cleanup()
        if stop_token and stop_token.should_stop():
            raise StopRequested("Stopped by user")

        self._prepare_generator(generator)
        self._collector_coordinator.start(collectors, logger)

        test_start_time = datetime.now()
        generator.start()
        logger.info("Running test for %s seconds", duration)

        test_end_time = self._wait_for_generator(
            generator, duration, test_name, repetition, stop_token
        )
        self._cleanup_after_run(generator, collectors)
        return test_start_time, test_end_time

    def _prepare_generator(self, generator: Any) -> None:
        prepare_generator(generator, self.config.warmup_seconds, logger)

    def _wait_for_generator(
        self,
        generator: Any,
        duration: int,
        test_name: str,
        repetition: int,
        stop_token: StopToken | None,
    ) -> datetime:
        return wait_for_generator(
            generator,
            duration,
            test_name,
            repetition,
            stop_token,
            logger,
        )

    def _cleanup_after_run(
        self, generator: Any, collectors: list[Any], generator_started: bool = True
    ) -> None:
        if generator_started and hasattr(generator, "stop"):
            try:
                if generator_running(generator):
                    logger.info("Stopping generator due to error or interruption...")
                generator.stop()
            except Exception as exc:
                logger.error("Failed to stop generator during cleanup: %s", exc)
        self._collector_coordinator.stop(collectors, logger)

    def _finalize_single_test(
        self,
        generator: Any,
        collectors: list[Any],
        workload_dir: Path,
        rep_dir: Path,
        test_name: str,
        repetition: int,
        total_repetitions: int,
        test_start_time: datetime | None,
        test_end_time: datetime | None,
    ) -> Dict[str, Any]:
        result = build_rep_result(
            test_name=test_name,
            repetition=repetition,
            rep_dir=rep_dir,
            generator_result=generator.get_result(),
            test_start_time=test_start_time,
            test_end_time=test_end_time,
        )
        duration_seconds = result.get("duration_seconds", 0) or 0
        if duration_seconds:
            logger.info("Repetition %s completed in %.2fs", repetition, duration_seconds)
        self._emit_progress(
            test_name,
            repetition,
            total_repetitions,
            "done" if result["success"] else "failed",
        )
        self._collector_coordinator.collect(
            collectors, workload_dir, rep_dir, test_name, repetition, result
        )
        self._result_persister.persist_rep_result(rep_dir, result)
        return result
    
    def _pre_test_cleanup(self) -> None:
        pre_test_cleanup(logger)
    
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
        logger.info(f"Starting benchmark: {test_type}")

        self._prepare_run_scope(run_id)

        if self.config.collect_system_info and not self.system_info:
            self.collect_system_info()

        workload_cfg = self._planner.resolve_workload(test_type)
        plugin: WorkloadPlugin = self.plugin_registry.get(workload_cfg.plugin)

        total_reps = total_repetitions or self.config.repetitions
        reps = self._planner.select_repetitions(repetition_override, pending_reps)

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

            if self._stop_token and self._stop_token.should_stop():
                break

        logger.info(f"Completed benchmark: {test_type}")
        return success_overall

    def _prepare_run_scope(self, run_id: str | None) -> None:
        scope = self._scope_manager.prepare(run_id)
        self._current_run_id = scope.run_id
        self._output_root = scope.output_root
        self._data_export_root = scope.data_export_root
        self._progress.set_run_id(scope.run_id)
        self._result_persister.set_run_id(scope.run_id)

    def _run_single_repetition(
        self,
        test_type: str,
        workload_cfg: WorkloadConfig,
        plugin: WorkloadPlugin,
        repetition: int,
        total_reps: int,
    ) -> bool:
        if self._stop_token and self._stop_token.should_stop():
            logger.info("Stop requested; aborting remaining repetitions.")
            self._emit_progress(test_type, repetition, total_reps, "stopped")
            return False

        logger.info("Starting repetition %s/%s", repetition, total_reps)
        config_input = self._planner.resolve_config_input(workload_cfg, plugin)

        try:
            generator = self.plugin_registry.create_generator(
                workload_cfg.plugin, config_input
            )
            self._emit_progress(test_type, repetition, total_reps, "running")
            result = self._run_single_test(
                test_name=test_type,
                generator=generator,
                repetition=repetition,
                total_repetitions=total_reps,
                stop_token=self._stop_token,
            )
            if isinstance(generator, BaseGenerator):
                self._cleanup_generator(generator, test_type, repetition)
            self._process_results(test_type, [result], plugin=plugin)
            return bool(result.get("success", True))
        except StopRequested:
            logger.info("Benchmark interrupted.")
            self._emit_progress(test_type, repetition, total_reps, "stopped")
            return False
        except Exception as exc:
            logger.error("Skipping workload '%s' on repetition %s: %s", test_type, repetition, exc)
            self._emit_progress(test_type, repetition, total_reps, "failed")
            return False

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
        self._result_persister.process_results(
            plugin=plugin,
            results=results,
            target_root=target_root,
            test_name=test_name,
        )

    def _emit_progress(
        self, test_name: str, repetition: int, total_repetitions: int, status: str
    ) -> None:
        """Notify progress callback and stdout marker for remote parsing."""
        self._progress.emit(test_name, repetition, total_repetitions, status)

    def run_all_benchmarks(self) -> None:
        """Run all configured benchmark tests."""
        run_id = self._planner.generate_run_id()
        for test_name, workload in self.config.workloads.items():
            if not workload.enabled:
                logger.info("Skipping disabled workload '%s'", test_name)
                continue
            try:
                self.run_benchmark(test_name, run_id=run_id)
            except Exception as e:
                logger.error(f"Failed to run {test_name} benchmark: {e}", exc_info=True)
