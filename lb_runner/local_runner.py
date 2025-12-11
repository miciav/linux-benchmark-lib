"""
Local controller module for managing the benchmark process.

This module coordinates the execution of workload generators and metric collectors,
managing the overall benchmark workflow.
"""

from __future__ import annotations

import json
import os
import logging
import platform
import subprocess
import time
from datetime import UTC, datetime
from json import JSONEncoder
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig
from lb_runner.data_handler_bridge import make_data_handler
from lb_runner.events import RunEvent, StdoutEmitter
from lb_runner.output_helpers import ensure_run_dirs, ensure_runner_log, write_system_info_artifacts
from lb_runner.plugin_system.registry import PluginRegistry
from lb_runner.plugin_system.interface import WorkloadIntensity, WorkloadPlugin
from lb_runner import system_info
logger = logging.getLogger(__name__)


class DateTimeEncoder(JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class LocalRunner:
    """Local agent for executing benchmarks on a single node."""
    
    def __init__(
        self,
        config: BenchmarkConfig,
        registry: PluginRegistry,
        progress_callback: Optional[Callable[[RunEvent], None]] = None,
        host_name: str | None = None,
    ):
        """
        Initialize the local runner.
        
        Args:
            config: Benchmark configuration
        """
        self.config = config
        collectors = {}
        if hasattr(registry, "available_collectors"):
            try:
                collectors = registry.available_collectors()
            except Exception:
                collectors = {}
        self.data_handler = make_data_handler(collectors)
        self.system_info: Optional[Dict[str, Any]] = None
        self.test_results: List[Dict[str, Any]] = []
        self.plugin_registry = registry
        self._current_run_id: Optional[str] = None
        self._output_root: Optional[Path] = None
        self._data_export_root: Optional[Path] = None
        self._log_file_handler_attached: bool = False
        self._progress_callback = progress_callback
        self._host_name = host_name or os.environ.get("LB_RUN_HOST") or platform.node() or "localhost"
        self._progress_emitter = StdoutEmitter()
        
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
    
    def _setup_collectors(self) -> List[Any]:
        """
        Set up metric collectors based on configuration.
        
        Returns:
            List of collector instances
        """
        return self.plugin_registry.create_collectors(self.config)
    
    def _run_single_test(
        self,
        test_name: str,
        generator: Any,
        repetition: int,
        total_repetitions: int,
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
        
        # Set up collectors
        collectors = self._setup_collectors()

        # Determine duration (allow workload to request a longer runtime)
        duration = self.config.test_duration_seconds
        if hasattr(generator, "expected_runtime_seconds"):
            try:
                expected = int(getattr(generator, "expected_runtime_seconds"))
                if expected > duration:
                    logger.info(
                        "Extending test duration to %s seconds based on workload hint",
                        expected,
                    )
                    duration = expected
            except Exception:
                logger.debug("Failed to read expected runtime from generator; using default duration")
        
        # Pre-test cleanup
        self._pre_test_cleanup()
        
        generator_started = False
        test_start_time = None
        test_end_time = None

        last_progress_log = 0

        try:
            # Run generator setup before metrics collection to avoid skew
            try:
                generator.prepare()
            except Exception as e:
                logger.error(f"Generator setup failed: {e}")
                raise

            # Warmup period
            if self.config.warmup_seconds > 0:
                logger.info(f"Warmup period: {self.config.warmup_seconds} seconds")
                time.sleep(self.config.warmup_seconds)

            # Start collectors
            for collector in collectors:
                try:
                    collector.start()
                except Exception as e:
                    logger.error(f"Failed to start collector {collector.name}: {e}")
            
            # Start workload generator
            test_start_time = datetime.now()
            generator.start()
            generator_started = True
            
            # Run for the specified duration
            logger.info(f"Running test for {duration} seconds")
            
            # Loop to wait for completion with a safety timeout
            safety_buffer = 10  # Allow 10 extra seconds for graceful exit
            max_wait = duration + safety_buffer
            elapsed = 0

            while elapsed < max_wait:
                if not getattr(generator, "_is_running", False):
                    break

                time.sleep(1)
                elapsed += 1

                # Emit lightweight progress logs for long runs
                if duration:
                    step = max(1, duration // 10)
                    percent = int((min(elapsed, duration) / duration) * 100)
                    if elapsed % step == 0 and elapsed != last_progress_log:
                        logger.info("Progress for %s rep %s: %s%%", test_name, repetition, percent)
                        last_progress_log = elapsed

            # Stop workload generator only if it's still running (timeout reached)
            if getattr(generator, "_is_running", False):
                logger.warning(f"Workload exceeded {max_wait}s (duration + safety). Forcing stop.")
                generator.stop()
                generator_started = False
            test_end_time = datetime.now()
            
            # Cooldown period
            if self.config.cooldown_seconds > 0:
                logger.info(f"Cooldown period: {self.config.cooldown_seconds} seconds")
                time.sleep(self.config.cooldown_seconds)

        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            raise

        finally:
            # Ensure generator is stopped if an error occurred while it was running
            if generator_started:
                try:
                    logger.info("Stopping generator due to error or interruption...")
                    generator.stop()
                except Exception as e:
                    logger.error(f"Failed to stop generator during cleanup: {e}")

            # Stop collectors
            for collector in collectors:
                try:
                    collector.stop()
                except Exception as e:
                    logger.error(f"Failed to stop collector {collector.name}: {e}")
        
        # Collect results
        duration_seconds = (
            (test_end_time - test_start_time).total_seconds()
            if test_start_time and test_end_time
            else 0
        )
        if duration_seconds:
            logger.info("Repetition %s completed in %.2fs", repetition, duration_seconds)

        result = {
            "test_name": test_name,
            "repetition": repetition,
            "start_time": test_start_time.isoformat() if test_start_time else None,
            "end_time": test_end_time.isoformat() if test_end_time else None,
            "duration_seconds": duration_seconds,
            "generator_result": generator.get_result(),
            "metrics": {}
        }
        gen_result = result["generator_result"]
        failed = False
        if isinstance(gen_result, dict):
            if gen_result.get("error"):
                failed = True
            rc = gen_result.get("returncode")
            if rc not in (None, 0):
                failed = True
        elif gen_result not in (None, 0, True):
            failed = True
        result["success"] = not failed
        # Emit per-repetition progress after completion
        self._emit_progress(test_name, repetition, total_repetitions, "done" if not failed else "failed")

        # Collect data from each collector
        for collector in collectors:
            collector_data = collector.get_data()
            result["metrics"][collector.name] = collector_data

            filename = f"{test_name}_rep{repetition}_{collector.name}.csv"
            target_root = self._output_root or self.config.output_dir
            filepath = target_root / filename
            collector.save_data(filepath)
        
        return result
    
    def _pre_test_cleanup(self) -> None:
        """Perform pre-test cleanup operations."""
        logger.info("Performing pre-test cleanup")
        
        if platform.system() == "Linux":
            # Clear filesystem caches
            try:
                subprocess.run(
                    ["sync"],
                    check=True
                )
                # Try to clear caches only if we have sudo access
                # In Docker containers, this often fails and that's OK
                try:
                    subprocess.run(
                        ["sudo", "-n", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
                        check=True,
                        capture_output=True
                    )
                    logger.info("Cleared filesystem caches")
                except Exception:
                    logger.debug("Skipping cache clearing (no sudo access)")
            except Exception as e:
                logger.warning(f"Failed to perform pre-test cleanup: {e}")

    def _emit_progress(self, test_name: str, repetition: int, total_repetitions: int, status: str) -> None:
        """Notify progress callback and stdout marker for remote parsing."""
        event = RunEvent(
            run_id=self._current_run_id or "",
            host=self._host_name,
            workload=test_name,
            repetition=repetition,
            total_repetitions=total_repetitions,
            status=status,
            timestamp=time.time(),
        )
        if self._progress_callback:
            try:
                self._progress_callback(event)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Progress callback failed: %s", exc)
        try:
            self._progress_emitter.emit(event)
        except Exception:
            # Never break workload on progress path
            pass
    
    def run_benchmark(
        self,
        test_type: str,
        repetition_override: int | None = None,
        total_repetitions: int | None = None,
        run_id: str | None = None,
    ) -> bool:
        """
        Run a complete benchmark test.
        
        Args:
            test_type: Name of the workload to run (plugin id)
            repetition_override: When set, run only this repetition index.
            total_repetitions: Total repetitions planned (for display purposes).
        """
        logger.info(f"Starting benchmark: {test_type}")

        run_identifier = run_id or self._generate_run_id()
        self._current_run_id = run_identifier
        self._output_root, self._data_export_root, _ = ensure_run_dirs(self.config, run_identifier)

        if not self._log_file_handler_attached and self._output_root:
            self._log_file_handler_attached = ensure_runner_log(self._output_root, logger)

        # Collect system info if enabled
        if self.config.collect_system_info and not self.system_info:
            self.collect_system_info()

        workload_cfg = self._resolve_workload(test_type)
        plugin_name = workload_cfg.plugin
        plugin: WorkloadPlugin = self.plugin_registry.get(plugin_name)

        # Run multiple repetitions
        test_results = []
        total_reps = total_repetitions or self.config.repetitions
        reps = (
            [repetition_override]
            if repetition_override is not None
            else list(range(1, self.config.repetitions + 1))
        )

        success_overall = True
        for rep in reps:
            if rep is None or rep <= 0:
                raise ValueError("Repetition index must be a positive integer")

            logger.info(f"Starting repetition {rep}/{total_reps}")

            try:
                # Determine configuration: Preset or User Options
                config_input = workload_cfg.options
                
                if workload_cfg.intensity and workload_cfg.intensity != "user_defined":
                    try:
                        level = WorkloadIntensity(workload_cfg.intensity)
                        preset_config = plugin.get_preset_config(level)
                        if preset_config:
                            logger.info(f"Using preset configuration for intensity '{level.value}'")
                            config_input = preset_config
                        else:
                            logger.warning(f"Plugin '{plugin_name}' does not support intensity '{level.value}', falling back to user options.")
                    except ValueError:
                        logger.warning(f"Invalid intensity level '{workload_cfg.intensity}', falling back to user options.")

                generator = self.plugin_registry.create_generator(
                    plugin_name, config_input
                )
                logger.info(
                    "==> Running workload '%s' (repetition %s/%s)",
                    test_type,
                    rep,
                    total_reps,
                )
                self._emit_progress(test_type, rep, total_reps, "running")
                result = self._run_single_test(
                    test_name=test_type,
                    generator=generator,
                    repetition=rep,
                    total_repetitions=total_reps,
                )
                test_results.append(result)
                if not result.get("success", True):
                    success_overall = False
                
            except Exception as e:
                logger.error(
                    f"Skipping workload '{test_type}' on repetition {rep}: {e}"
                )
                success_overall = False
                self._emit_progress(test_type, rep, total_reps, "failed")
                break
        
        # Process and save results
        if test_results:
            self._process_results(test_type, test_results, plugin=plugin)
        
        logger.info(f"Completed benchmark: {test_type}")
        return success_overall
    
    def _process_results(self, test_name: str, results: List[Dict[str, Any]], plugin: WorkloadPlugin | None = None) -> None:
        """
        Process and save test results.
        
        Args:
            test_name: Name of the test
            results: List of test results
        """
        # Save raw results
        target_root = self._output_root or self.config.output_dir
        export_root = self._data_export_root or self.config.data_export_dir
        results_file = target_root / f"{test_name}_results.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2, cls=DateTimeEncoder)
        
        logger.info(f"Saved raw results to {results_file}")
        
        # Process data using DataHandler
        aggregated_df = self.data_handler.process_test_results(test_name, results)
        
        # Save aggregated results
        if aggregated_df is not None:
            csv_file = export_root / f"{test_name}_aggregated.csv"
            aggregated_df.to_csv(csv_file)
            logger.info(f"Saved aggregated results to {csv_file}")

        # Allow plugin-specific CSV exports for raw generator outputs
        if plugin:
            try:
                exported = plugin.export_results_to_csv(
                    results=results,
                    output_dir=target_root,
                    run_id=self._current_run_id or "",
                    test_name=test_name,
                )
                for path in exported:
                    logger.info("Plugin exported CSV: %s", path)
            except Exception as exc:
                logger.warning("Plugin '%s' export_results_to_csv failed: %s", plugin.name, exc)

    def _resolve_workload(self, name: str) -> WorkloadConfig:
        """Return the workload configuration ensuring it is enabled."""
        workload = self.config.workloads.get(name)
        if workload is None:
            raise ValueError(f"Unknown workload: {name}")
        if not workload.enabled:
            raise ValueError(f"Workload '{name}' is disabled in the configuration")
        return workload

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a timestamp-based run id."""
        return datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S")
    
    def run_all_benchmarks(self) -> None:
        """Run all configured benchmark tests."""
        run_id = self._generate_run_id()
        for test_name, workload in self.config.workloads.items():
            if not workload.enabled:
                logger.info("Skipping disabled workload '%s'", test_name)
                continue
            try:
                self.run_benchmark(test_name, run_id=run_id)
            except Exception as e:
                logger.error(f"Failed to run {test_name} benchmark: {e}", exc_info=True)
