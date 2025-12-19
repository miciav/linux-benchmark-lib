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
import shutil
from datetime import UTC, datetime
from json import JSONEncoder
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig
from lb_runner.events import RunEvent, StdoutEmitter
from lb_runner.log_handler import LBEventLogHandler
from lb_runner.output_helpers import (
    ensure_run_dirs,
    ensure_runner_log,
    workload_output_dir,
    write_system_info_artifacts,
)
from lb_runner.plugin_system.registry import PluginRegistry
from lb_runner.plugin_system.interface import WorkloadIntensity, WorkloadPlugin
from lb_runner.plugin_system.base_generator import BaseGenerator
from lb_runner.stop_token import StopToken
from lb_runner import system_info
logger = logging.getLogger(__name__)


class DateTimeEncoder(JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class StopRequested(Exception):
    """Raised when execution is stopped by user request."""
    pass


class LocalRunner:
    """Local agent for executing benchmarks on a single node."""
    
    def __init__(
        self,
        config: BenchmarkConfig,
        registry: PluginRegistry,
        progress_callback: Optional[Callable[[RunEvent], None]] = None,
        host_name: str | None = None,
        stop_token: StopToken | None = None,
    ):
        """
        Initialize the local runner.
        
        Args:
            config: Benchmark configuration
        """
        self.config = config
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
        self._stop_token = stop_token
        
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
        collectors = self._setup_collectors()
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
                logger.debug(
                    "Failed to read expected runtime from generator; using default duration"
                )
        return duration

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
        self._start_collectors(collectors)

        test_start_time = datetime.now()
        generator.start()
        logger.info("Running test for %s seconds", duration)

        test_end_time = self._wait_for_generator(
            generator, duration, test_name, repetition, stop_token
        )
        self._cleanup_after_run(generator, collectors)
        return test_start_time, test_end_time

    def _prepare_generator(self, generator: Any) -> None:
        try:
            generator.prepare()
        except Exception as e:
            logger.error("Generator setup failed: %s", e)
            raise
        if self.config.warmup_seconds > 0:
            logger.info("Warmup period: %s seconds", self.config.warmup_seconds)
            time.sleep(self.config.warmup_seconds)

    def _start_collectors(self, collectors: list[Any]) -> None:
        for collector in collectors:
            try:
                collector.start()
            except Exception as e:
                logger.error("Failed to start collector %s: %s", collector.name, e)

    def _wait_for_generator(
        self,
        generator: Any,
        duration: int,
        test_name: str,
        repetition: int,
        stop_token: StopToken | None,
    ) -> datetime:
        safety_buffer = 10
        max_wait = duration + safety_buffer
        elapsed = 0
        last_progress_log = 0
        while elapsed < max_wait:
            if stop_token and stop_token.should_stop():
                raise StopRequested("Stopped by user")
            if not self._generator_running(generator):
                break
            time.sleep(1)
            elapsed += 1
            if self._should_log_progress(duration, elapsed, last_progress_log):
                percent = int((min(elapsed, duration) / duration) * 100)
                logger.info(
                    "Progress for %s rep %s: %s%%", test_name, repetition, percent
                )
                last_progress_log = elapsed
        if self._generator_running(generator):
            logger.warning(
                "Workload exceeded %ss (duration + safety). Forcing stop.", max_wait
            )
            generator.stop()
        return datetime.now()

    @staticmethod
    def _should_log_progress(duration: int, elapsed: int, last_progress_log: int) -> bool:
        if not duration:
            return False
        step = max(1, duration // 10)
        return elapsed % step == 0 and elapsed != last_progress_log

    def _cleanup_after_run(
        self, generator: Any, collectors: list[Any], generator_started: bool = True
    ) -> None:
        try:
            if generator_started and self._generator_running(generator):
                logger.info("Stopping generator due to error or interruption...")
                generator.stop()
        except Exception as e:
            logger.error("Failed to stop generator during cleanup: %s", e)

        for collector in collectors:
            try:
                collector.stop()
            except Exception as e:
                logger.error("Failed to stop collector %s: %s", collector.name, e)

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
            "metrics": {},
            "artifacts_dir": str(rep_dir),
        }
        result["success"] = self._is_generator_success(result["generator_result"])
        self._emit_progress(
            test_name, repetition, total_repetitions, "done" if result["success"] else "failed"
        )
        self._collect_metrics(collectors, workload_dir, rep_dir, test_name, repetition, result)
        self._persist_rep_result(rep_dir, result)
        return result

    @staticmethod
    def _is_generator_success(gen_result: Any) -> bool:
        if isinstance(gen_result, dict):
            if gen_result.get("error"):
                return False
            rc = gen_result.get("returncode")
            return rc in (None, 0)
        return gen_result in (None, 0, True)

    def _collect_metrics(
        self,
        collectors: list[Any],
        workload_dir: Path,
        rep_dir: Path,
        test_name: str,
        repetition: int,
        result: Dict[str, Any],
    ) -> None:
        for collector in collectors:
            collector_data = collector.get_data()
            result["metrics"][collector.name] = collector_data
            filename = f"{test_name}_rep{repetition}_{collector.name}.csv"
            filepath = workload_dir / filename
            collector.save_data(filepath)
            rep_filepath = rep_dir / filename
            try:
                if rep_filepath != filepath:
                    shutil.copyfile(filepath, rep_filepath)
            except Exception:
                pass

    @staticmethod
    def _persist_rep_result(rep_dir: Path, result: Dict[str, Any]) -> None:
        try:
            rep_result_path = rep_dir / "result.json"
            rep_result_path.write_text(
                json.dumps(result, indent=2, cls=DateTimeEncoder)
            )
        except Exception:
            pass
    
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

    @staticmethod
    def _generator_running(generator: Any) -> bool:
        """
        Safely interpret the generator's running flag.

        MagicMock instances used in tests may return a non-bool sentinel for
        `_is_running`; treat any non-bool as False to avoid long sleep loops.
        """
        state = getattr(generator, "_is_running", False)
        return state is True or (isinstance(state, bool) and state)
    
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

        workload_cfg = self._resolve_workload(test_type)
        plugin: WorkloadPlugin = self.plugin_registry.get(workload_cfg.plugin)

        total_reps = total_repetitions or self.config.repetitions
        reps = self._select_repetitions(repetition_override, pending_reps)

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
        run_identifier = run_id or self._generate_run_id()
        self._current_run_id = run_identifier
        self._output_root, self._data_export_root, _ = ensure_run_dirs(
            self.config, run_identifier
        )
        if not self._log_file_handler_attached and self._output_root:
            self._log_file_handler_attached = ensure_runner_log(
                self._output_root, logger
            )

    def _select_repetitions(
        self, repetition_override: int | None, pending_reps: List[int] | None
    ) -> List[int]:
        if pending_reps:
            reps = pending_reps
        elif repetition_override is not None:
            reps = [repetition_override]
        else:
            reps = list(range(1, self.config.repetitions + 1))
        for rep in reps:
            if rep is None or rep <= 0:
                raise ValueError("Repetition index must be a positive integer")
        return reps

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
        config_input = self._resolve_config_input(workload_cfg, plugin)

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

    def _resolve_config_input(
        self, workload_cfg: WorkloadConfig, plugin: WorkloadPlugin
    ) -> Any:
        config_input: Any = workload_cfg.options
        if workload_cfg.intensity and workload_cfg.intensity != "user_defined":
            try:
                level = WorkloadIntensity(workload_cfg.intensity)
                preset_config = plugin.get_preset_config(level)
                if preset_config:
                    logger.info("Using preset configuration for intensity '%s'", level.value)
                    return preset_config
                logger.warning(
                    "Plugin '%s' does not support intensity '%s', falling back to user options.",
                    plugin.name,
                    level.value,
                )
            except ValueError:
                logger.warning(
                    "Invalid intensity level '%s', falling back to user options.",
                    workload_cfg.intensity,
                )
        return config_input

    def _cleanup_generator(
        self, generator: BaseGenerator, test_type: str, repetition: int
    ) -> None:
        try:
            generator.cleanup()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.warning(
                "Generator cleanup failed for %s rep %s: %s", test_type, repetition, exc
            )
    
    def _process_results(self, test_name: str, results: List[Dict[str, Any]], plugin: WorkloadPlugin | None = None) -> None:
        """Process and save test results."""
        target_root = self._workload_output_dir(test_name)
        results_file = target_root / f"{test_name}_results.json"

        merged_results = self._merge_results(results_file, results)
        self._persist_results(results_file, merged_results)
        self._export_plugin_results(plugin, merged_results, target_root, test_name)

    def _merge_results(
        self, results_file: Path, new_results: List[Dict[str, Any]]
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        if results_file.exists():
            try:
                existing_raw = json.loads(results_file.read_text())
                if isinstance(existing_raw, list):
                    merged = [r for r in existing_raw if isinstance(r, dict)]
            except Exception:
                merged = []

        def _rep_key(entry: dict[str, Any]) -> int | None:
            rep_val = entry.get("repetition")
            return rep_val if isinstance(rep_val, int) and rep_val > 0 else None

        merged_by_rep: dict[int, dict[str, Any]] = {
            rep: entry for entry in merged if (rep := _rep_key(entry)) is not None
        }
        unkeyed: list[dict[str, Any]] = [e for e in merged if _rep_key(e) is None]
        for entry in new_results:
            rep = _rep_key(entry)
            if rep is None:
                unkeyed.append(entry)
            else:
                merged_by_rep[rep] = entry

        return [merged_by_rep[rep] for rep in sorted(merged_by_rep)] + unkeyed

    def _persist_results(self, results_file: Path, merged_results: list[dict[str, Any]]) -> None:
        tmp_path = results_file.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(merged_results, indent=2, cls=DateTimeEncoder))
        tmp_path.replace(results_file)
        logger.info("Saved raw results to %s", results_file)
    
    def _export_plugin_results(
        self,
        plugin: WorkloadPlugin | None,
        merged_results: list[dict[str, Any]],
        target_root: Path,
        test_name: str,
    ) -> None:
        if not plugin:
            return
        try:
            exported = plugin.export_results_to_csv(
                results=merged_results,
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
