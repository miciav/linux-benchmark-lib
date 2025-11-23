"""
Orchestrator module for managing the benchmark process.

This module coordinates the execution of workload generators and metric collectors,
managing the overall benchmark workflow.
"""

from __future__ import annotations

import json
import logging
import platform
import subprocess
import time
from datetime import datetime
from json import JSONEncoder
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark_config import BenchmarkConfig, WorkloadConfig
from data_handler import DataHandler
from metric_collectors import CLICollector, EBPFCollector, PSUtilCollector, PerfCollector
from plugins.builtin import builtin_plugins
from plugins.registry import PluginRegistry, print_plugin_table
from workload_generators import DDGenerator, FIOGenerator, IPerf3Generator, StressNGGenerator


logger = logging.getLogger(__name__)


class DateTimeEncoder(JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class LocalRunner:
    """Local agent for executing benchmarks on a single node."""
    
    def __init__(self, config: BenchmarkConfig, registry: PluginRegistry | None = None):
        """
        Initialize the local runner.
        
        Args:
            config: Benchmark configuration
        """
        self.config = config
        self.data_handler = DataHandler()
        self.system_info: Optional[Dict[str, Any]] = None
        self.test_results: List[Dict[str, Any]] = []
        self.plugin_registry = registry or PluginRegistry(builtin_plugins())
        self._print_available_plugins()
        
    def collect_system_info(self) -> Dict[str, Any]:
        """
        Collect detailed information about the system.
        
        Returns:
            Dictionary containing system information
        """
        logger.info("Collecting system information")
        
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
        
        # Collect additional Linux-specific information
        if platform.system() == "Linux":
            # CPU information
            try:
                with open("/proc/cpuinfo", "r") as f:
                    cpuinfo = f.read()
                    # Extract model name
                    for line in cpuinfo.split("\n"):
                        if "model name" in line:
                            info["cpu_model"] = line.split(":")[1].strip()
                            break
                    # Count physical cores
                    info["cpu_cores"] = len(set(line.split(":")[1].strip() 
                                               for line in cpuinfo.split("\n") 
                                               if "physical id" in line))
            except:
                pass
            
            # Memory information
            try:
                with open("/proc/meminfo", "r") as f:
                    meminfo = f.read()
                    for line in meminfo.split("\n"):
                        if "MemTotal" in line:
                            info["memory_total_kb"] = int(line.split()[1])
                            break
            except:
                pass
            
            # Distribution information
            try:
                result = subprocess.run(
                    ["lsb_release", "-a"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    info["distribution"] = result.stdout
            except:
                pass
        
        self.system_info = info
        return info
    
    def _setup_collectors(self) -> List[Any]:
        """
        Set up metric collectors based on configuration.
        
        Returns:
            List of collector instances
        """
        collectors = []
        
        # Always add PSUtil collector
        collectors.append(
            PSUtilCollector(
                interval_seconds=(
                    self.config.collectors.psutil_interval
                    or self.config.metrics_interval_seconds
                )
            )
        )
        
        # Add CLI collector if commands are specified
        if self.config.collectors.cli_commands:
            collectors.append(
                CLICollector(
                    interval_seconds=self.config.metrics_interval_seconds,
                    commands=self.config.collectors.cli_commands
                )
            )
        
        # Add Perf collector if events are specified
        if self.config.collectors.perf_config.events:
            collectors.append(
                PerfCollector(
                    interval_seconds=self.config.metrics_interval_seconds,
                    events=self.config.collectors.perf_config.events
                )
            )
        
        # Add eBPF collector if enabled
        if self.config.collectors.enable_ebpf:
            collectors.append(
                EBPFCollector(
                    interval_seconds=self.config.metrics_interval_seconds
                )
            )
        
        return collectors
    
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
        try:
            generator.start()
        except Exception as e:
            logger.error(f"Failed to start generator: {e}")
            # Stop collectors
            for collector in collectors:
                collector.stop()
            raise
        
        # Run for the specified duration
        logger.info(f"Running test for {self.config.test_duration_seconds} seconds")
        
        # Loop to provide progress feedback
        duration = self.config.test_duration_seconds
        for i in range(duration):
            time.sleep(1)
            # Calculate percentage
            percent = int(((i + 1) / duration) * 100)
            # Print progress marker for the orchestrator to pick up
            # We use print directly to ensure it goes to stdout cleanly for parsing
            if duration < 10 or (i + 1) % 5 == 0 or (i + 1) == duration:
                print(f"BENCHMARK_PROGRESS: {percent}%", flush=True)
        
        # Stop workload generator
        generator.stop()
        test_end_time = datetime.now()
        
        # Cooldown period
        if self.config.cooldown_seconds > 0:
            logger.info(f"Cooldown period: {self.config.cooldown_seconds} seconds")
            time.sleep(self.config.cooldown_seconds)
        
        # Stop collectors
        for collector in collectors:
            collector.stop()
        
        # Collect results
        result = {
            "test_name": test_name,
            "repetition": repetition,
            "start_time": test_start_time.isoformat(),
            "end_time": test_end_time.isoformat(),
            "duration_seconds": (test_end_time - test_start_time).total_seconds(),
            "generator_result": generator.get_result(),
            "metrics": {}
        }
        
        # Collect data from each collector
        for collector in collectors:
            collector_data = collector.get_data()
            result["metrics"][collector.name] = collector_data
            
            # Save raw data
            filename = f"{test_name}_rep{repetition}_{collector.name}.csv"
            filepath = self.config.output_dir / filename
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
                except:
                    logger.debug("Skipping cache clearing (no sudo access)")
            except Exception as e:
                logger.warning(f"Failed to perform pre-test cleanup: {e}")
    
    def run_benchmark(self, test_type: str) -> None:
        """
        Run a complete benchmark test.
        
        Args:
            test_type: Name of the workload to run (plugin id)
        """
        logger.info(f"Starting benchmark: {test_type}")
        
        # Collect system info if enabled
        if self.config.collect_system_info and not self.system_info:
            self.collect_system_info()

        workload_cfg = self._resolve_workload(test_type)
        plugin_name = workload_cfg.plugin

        # Run multiple repetitions
        test_results = []
        for rep in range(1, self.config.repetitions + 1):
            logger.info(f"Starting repetition {rep}/{self.config.repetitions}")
            
            try:
                generator = self.plugin_registry.create_generator(
                    plugin_name, workload_cfg.options
                )
                result = self._run_single_test(
                    test_name=test_type,
                    generator=generator,
                    repetition=rep
                )
                test_results.append(result)
                
            except Exception as e:
                logger.error(f"Test failed on repetition {rep}: {e}", exc_info=True)
                continue
        
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
        results_file = self.config.output_dir / f"{test_name}_results.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2, cls=DateTimeEncoder)
        
        logger.info(f"Saved raw results to {results_file}")
        
        # Process data using DataHandler
        aggregated_df = self.data_handler.process_test_results(test_name, results)
        
        # Save aggregated results
        if aggregated_df is not None:
            csv_file = self.config.data_export_dir / f"{test_name}_aggregated.csv"
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

    def _print_available_plugins(self) -> None:
        """Print the available workload plugins at startup."""
        enabled = {name: wl.enabled for name, wl in self.config.workloads.items()}
        print_plugin_table(self.plugin_registry, enabled=enabled)
    
    def run_all_benchmarks(self) -> None:
        """Run all configured benchmark tests."""
        for test_name, workload in self.config.workloads.items():
            if not workload.enabled:
                logger.info("Skipping disabled workload '%s'", test_name)
                continue
            try:
                self.run_benchmark(test_name)
            except Exception as e:
                logger.error(f"Failed to run {test_name} benchmark: {e}", exc_info=True)
