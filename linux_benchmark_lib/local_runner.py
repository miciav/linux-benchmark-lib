"""
Local controller module for managing the benchmark process.

This module coordinates the execution of workload generators and metric collectors,
managing the overall benchmark workflow.
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import time
import sys
from datetime import UTC, datetime
from json import JSONEncoder
from pathlib import Path
from typing import Any, Dict, List, Optional

from .benchmark_config import BenchmarkConfig, WorkloadConfig
from .data_handler import DataHandler
from .plugin_system.registry import PluginRegistry, print_plugin_table
from .plugin_system.interface import WorkloadIntensity
from .ui import get_ui_adapter
from .ui.types import UIAdapter


logger = logging.getLogger(__name__)


class DateTimeEncoder(JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class LocalRunner:
    """Local agent for executing benchmarks on a single node."""
    
    def __init__(self, config: BenchmarkConfig, registry: PluginRegistry, ui_adapter: UIAdapter | None = None):
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
        self.data_handler = DataHandler(collectors=collectors)
        self.system_info: Optional[Dict[str, Any]] = None
        self.test_results: List[Dict[str, Any]] = []
        self.plugin_registry = registry
        self.ui = ui_adapter or get_ui_adapter()
        self._current_run_id: Optional[str] = None
        self._output_root: Optional[Path] = None
        self._data_export_root: Optional[Path] = None
        
    def collect_system_info(self) -> Dict[str, Any]:
        """
        Collect detailed information about the system.
        
        Returns:
            Dictionary containing system information
        """
        logger.info("Collecting system information")
        
        try:
            import psutil
        except ImportError:
            logger.warning("psutil not found, system info will be limited")
            psutil = None

        info = {
            "timestamp": datetime.now().isoformat(),
            "platform": {
                "system": platform.system(),
                "node": platform.node(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
            },
            "python": {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
            }
        }
        
        if psutil:
            # CPU information via psutil
            try:
                info["cpu_count_logical"] = psutil.cpu_count(logical=True)
                info["cpu_count_physical"] = psutil.cpu_count(logical=False)
                # Frequency might be None on some systems
                freq = psutil.cpu_freq()
                if freq:
                    info["cpu_freq_current"] = freq.current
                    info["cpu_freq_min"] = freq.min
                    info["cpu_freq_max"] = freq.max
            except Exception as e:
                logger.debug(f"Failed to collect CPU info via psutil: {e}")

            # Memory information via psutil
            try:
                vm = psutil.virtual_memory()
                info["memory_total_bytes"] = vm.total
                info["memory_available_bytes"] = vm.available
                swap = psutil.swap_memory()
                info["swap_total_bytes"] = swap.total
            except Exception as e:
                logger.debug(f"Failed to collect memory info via psutil: {e}")

        # Collect additional Linux-specific information (Distribution)
        if platform.system() == "Linux":
            try:
                # robustly check for lsb_release
                if shutil.which("lsb_release"):
                    result = subprocess.run(
                        ["lsb_release", "-a"],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        info["distribution"] = result.stdout.strip()
            except Exception as e:
                logger.debug(f"Failed to collect distribution info: {e}")
        
        self.system_info = info
        return info
    
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
        repetition: int
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
        
        # Pre-test cleanup
        self._pre_test_cleanup()
        
        generator_started = False
        test_start_time = None
        test_end_time = None

        progress = None

        try:
            progress = self.ui.create_progress(
                f"{test_name} (rep {repetition})",
                total=self.config.test_duration_seconds,
            )

            # Start collectors
            for collector in collectors:
                try:
                    collector.start()
                except Exception as e:
                    logger.error(f"Failed to start collector {collector.name}: {e}")
            
            # Warmup period
            if self.config.warmup_seconds > 0:
                logger.info(f"Warmup period: {self.config.warmup_seconds} seconds")
                time.sleep(self.config.warmup_seconds)
            
            # Start workload generator
            test_start_time = datetime.now()
            generator.start()
            generator_started = True
            
            # Run for the specified duration
            logger.info(f"Running test for {self.config.test_duration_seconds} seconds")
            
            # Loop to wait for completion with a safety timeout
            duration = self.config.test_duration_seconds
            safety_buffer = 10  # Allow 10 extra seconds for graceful exit
            max_wait = duration + safety_buffer
            elapsed = 0

            while elapsed < max_wait:
                if not getattr(generator, "_is_running", False):
                    break

                time.sleep(1)
                elapsed += 1

                # Update progress (cap at duration to keep bar clean)
                if progress:
                    progress.update(min(elapsed, duration))
                else:
                    step = max(1, duration // 10)
                    percent = int((min(elapsed, duration) / duration) * 100)
                    if elapsed % step == 0:
                        self.ui.show_info(f"Progress: {percent}%")

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
            if progress:
                progress.finish()
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
        result = {
            "test_name": test_name,
            "repetition": repetition,
            "start_time": test_start_time.isoformat() if test_start_time else None,
            "end_time": test_end_time.isoformat() if test_end_time else None,
            "duration_seconds": (test_end_time - test_start_time).total_seconds() if test_start_time and test_end_time else 0,
            "generator_result": generator.get_result(),
            "metrics": {}
        }
        
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
    
    def run_benchmark(
        self,
        test_type: str,
        repetition_override: int | None = None,
        total_repetitions: int | None = None,
        run_id: str | None = None,
    ) -> None:
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
        self._output_root, self._data_export_root, _ = self._ensure_directories(run_identifier)
        
        # Collect system info if enabled
        if self.config.collect_system_info and not self.system_info:
            self.collect_system_info()

        workload_cfg = self._resolve_workload(test_type)
        plugin_name = workload_cfg.plugin

        # Run multiple repetitions
        test_results = []
        total_reps = total_repetitions or self.config.repetitions
        reps = (
            [repetition_override]
            if repetition_override is not None
            else list(range(1, self.config.repetitions + 1))
        )

        for rep in reps:
            if rep is None or rep <= 0:
                raise ValueError("Repetition index must be a positive integer")

            logger.info(f"Starting repetition {rep}/{total_reps}")
            
            try:
                plugin = self.plugin_registry.get(plugin_name)
                
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
                self.ui.show_info(
                    f"==> Running workload '{test_type}' (repetition {rep}/{total_reps})"
                )
                result = self._run_single_test(
                    test_name=test_type,
                    generator=generator,
                    repetition=rep
                )
                test_results.append(result)
                
            except Exception as e:
                logger.error(
                    f"Skipping workload '{test_type}' on repetition {rep}: {e}"
                )
                break
        
        # Process and save results
        if test_results:
            self._process_results(test_type, test_results)
        
        logger.info(f"Completed benchmark: {test_type}")
    
    def _process_results(self, test_name: str, results: List[Dict[str, Any]]) -> None:
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

    def _resolve_workload(self, name: str) -> WorkloadConfig:
        """Return the workload configuration ensuring it is enabled."""
        workload = self.config.workloads.get(name)
        if workload is None:
            raise ValueError(f"Unknown workload: {name}")
        if not workload.enabled:
            raise ValueError(f"Workload '{name}' is disabled in the configuration")
        return workload

    def _ensure_directories(self, run_id: str) -> tuple[Path, Path, Path]:
        """Create required local output directories for a run."""
        self.config.ensure_output_dirs()
        output_root = (self.config.output_dir / run_id).resolve()
        report_root = (self.config.report_dir / run_id).resolve()
        data_export_root = (self.config.data_export_dir / run_id).resolve()
        for path in (output_root, report_root, data_export_root):
            path.mkdir(parents=True, exist_ok=True)
        return output_root, data_export_root, report_root

    def _print_available_plugins(self) -> None:
        """Print the available workload plugins at startup."""
        enabled = {name: wl.enabled for name, wl in self.config.workloads.items()}
        print_plugin_table(self.plugin_registry, enabled=enabled, ui_adapter=self.ui)

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
