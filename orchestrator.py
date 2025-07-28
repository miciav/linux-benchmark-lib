"""
Orchestrator module for managing the benchmark process.

This module coordinates the execution of workload generators and metric collectors,
managing the overall benchmark workflow.
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import platform
import subprocess
import json
from json import JSONEncoder

from benchmark_config import BenchmarkConfig
from metric_collectors import PSUtilCollector, CLICollector, PerfCollector, EBPFCollector
from workload_generators import StressNGGenerator, IPerf3Generator, DDGenerator, FIOGenerator
from data_handler import DataHandler


logger = logging.getLogger(__name__)


class DateTimeEncoder(JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class Orchestrator:
    """Main orchestrator for benchmark execution."""
    
    def __init__(self, config: BenchmarkConfig):
        """
        Initialize the orchestrator.
        
        Args:
            config: Benchmark configuration
        """
        self.config = config
        self.data_handler = DataHandler()
        self.system_info: Optional[Dict[str, Any]] = None
        self.test_results: List[Dict[str, Any]] = []
        
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
                interval_seconds=self.config.metrics_interval_seconds
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
        time.sleep(self.config.test_duration_seconds)
        
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
            test_type: Type of test to run ('stress_ng', 'iperf3', 'dd', 'fio')
        """
        logger.info(f"Starting benchmark: {test_type}")
        
        # Collect system info if enabled
        if self.config.collect_system_info and not self.system_info:
            self.collect_system_info()
        
        # Create generator based on test type
        if test_type == "stress_ng":
            generator_class = StressNGGenerator
            generator_config = self.config.stress_ng
        elif test_type == "iperf3":
            generator_class = IPerf3Generator
            generator_config = self.config.iperf3
        elif test_type == "dd":
            generator_class = DDGenerator
            generator_config = self.config.dd
        elif test_type == "fio":
            generator_class = FIOGenerator
            generator_config = self.config.fio
        else:
            raise ValueError(f"Unknown test type: {test_type}")
        
        # Run multiple repetitions
        test_results = []
        for rep in range(1, self.config.repetitions + 1):
            logger.info(f"Starting repetition {rep}/{self.config.repetitions}")
            
            try:
                generator = generator_class(generator_config)
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
    
    def run_all_benchmarks(self) -> None:
        """Run all configured benchmark tests."""
        test_types = ["stress_ng", "iperf3", "dd", "fio"]
        
        for test_type in test_types:
            try:
                self.run_benchmark(test_type)
            except Exception as e:
                logger.error(f"Failed to run {test_type} benchmark: {e}", exc_info=True)
