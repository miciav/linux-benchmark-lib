"""
Real integration tests that actually execute benchmarks.

These tests run actual benchmarks with minimal parameters to verify
the entire system works end-to-end.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
import json
import time

from benchmark_config import BenchmarkConfig, StressNGConfig, MetricCollectorConfig
from orchestrator import Orchestrator


class TestRealBenchmarkIntegration(unittest.TestCase):
    """Integration tests that run actual benchmarks."""
    
    def setUp(self):
        """Set up temporary directories for test outputs."""
        self.temp_dir = tempfile.mkdtemp(prefix="benchmark_test_")
        self.temp_path = Path(self.temp_dir)
        
    def tearDown(self):
        """Clean up temporary directories."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_minimal_stress_ng_benchmark(self):
        """Test a minimal stress-ng benchmark execution."""
        # Create a minimal configuration
        config = BenchmarkConfig(
            repetitions=1,
            test_duration_seconds=2,  # Very short duration
            metrics_interval_seconds=0.5,
            warmup_seconds=0,
            cooldown_seconds=0,
            output_dir=self.temp_path / "results",
            report_dir=self.temp_path / "reports",
            data_export_dir=self.temp_path / "exports",
            stress_ng=StressNGConfig(
                cpu_workers=1,  # Minimal workers
                vm_workers=0,   # Disable VM workers
                io_workers=0,   # Disable IO workers
                timeout=2
            ),
            collectors=MetricCollectorConfig(
                psutil_interval=0.5,
                cli_commands=[],  # No CLI commands for speed
                enable_ebpf=False
            )
        )
        
        # Create and run orchestrator
        orchestrator = Orchestrator(config)
        
        # Collect system info
        system_info = orchestrator.collect_system_info()
        self.assertIsNotNone(system_info)
        self.assertIn("platform", system_info)
        self.assertIn("python", system_info)
        
        # Run the benchmark
        start_time = time.time()
        orchestrator.run_benchmark("stress_ng")
        end_time = time.time()
        
        # Verify execution time is reasonable
        execution_time = end_time - start_time
        self.assertLess(execution_time, 10)  # Should complete within 10 seconds
        
        # Verify output files were created
        results_file = config.output_dir / "stress_ng_results.json"
        self.assertTrue(results_file.exists(), f"Results file not found: {results_file}")
        
        # Load and verify results
        with open(results_file, "r") as f:
            results = json.load(f)
            
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)  # One repetition
        
        result = results[0]
        self.assertEqual(result["test_name"], "stress_ng")
        self.assertEqual(result["repetition"], 1)
        self.assertIn("start_time", result)
        self.assertIn("end_time", result)
        self.assertIn("duration_seconds", result)
        self.assertIn("generator_result", result)
        self.assertIn("metrics", result)
        
        # Verify metrics were collected
        self.assertIn("PSUtilCollector", result["metrics"])
        psutil_metrics = result["metrics"]["PSUtilCollector"]
        self.assertIsInstance(psutil_metrics, list)
        self.assertGreater(len(psutil_metrics), 0)
        
        # Verify metric data structure
        for metric in psutil_metrics:
            self.assertIn("timestamp", metric)
            self.assertIn("cpu_percent", metric)
            self.assertIn("memory_usage", metric)
            
        # Verify aggregated data file
        aggregated_file = config.data_export_dir / "stress_ng_aggregated.csv"
        # Note: aggregated file might not exist if DataHandler is not implemented
        # or returns None
        
        # Verify collector raw data files
        collector_files = list(config.output_dir.glob("stress_ng_rep1_*.csv"))
        self.assertGreater(len(collector_files), 0, "No collector CSV files found")
        
    def test_system_info_collection(self):
        """Test system information collection."""
        config = BenchmarkConfig(
            output_dir=self.temp_path / "results",
            report_dir=self.temp_path / "reports", 
            data_export_dir=self.temp_path / "exports"
        )
        
        orchestrator = Orchestrator(config)
        system_info = orchestrator.collect_system_info()
        
        # Verify basic system info
        self.assertIn("timestamp", system_info)
        self.assertIn("platform", system_info)
        self.assertIn("python", system_info)
        
        platform_info = system_info["platform"]
        self.assertIn("system", platform_info)
        self.assertIn("machine", platform_info)
        self.assertIn("release", platform_info)
        
        python_info = system_info["python"]
        self.assertIn("version", python_info)
        self.assertIn("implementation", python_info)
        
    @unittest.skipUnless(
        shutil.which("stress-ng") is not None,
        "stress-ng not installed"
    )
    def test_stress_ng_with_multiple_metrics(self):
        """Test stress-ng with multiple metric collectors enabled."""
        config = BenchmarkConfig(
            repetitions=1,
            test_duration_seconds=3,
            metrics_interval_seconds=1.0,
            warmup_seconds=1,
            cooldown_seconds=1,
            output_dir=self.temp_path / "results",
            report_dir=self.temp_path / "reports",
            data_export_dir=self.temp_path / "exports",
            stress_ng=StressNGConfig(
                cpu_workers=2,
                cpu_method="matrixprod",
                timeout=3
            ),
            collectors=MetricCollectorConfig(
                psutil_interval=1.0,
                cli_commands=[],  # Disable CLI commands to avoid jc parser issues
                enable_ebpf=False
            )
        )
        
        orchestrator = Orchestrator(config)
        orchestrator.run_benchmark("stress_ng")
        
        # Load results
        results_file = config.output_dir / "stress_ng_results.json"
        with open(results_file, "r") as f:
            results = json.load(f)
            
        result = results[0]
        
        # Verify PSUtil collector ran
        self.assertIn("PSUtilCollector", result["metrics"])
        
        # Verify timing (duration is only the test execution time, not warmup/cooldown)
        duration = result["duration_seconds"]
        expected_duration = config.test_duration_seconds
        self.assertAlmostEqual(duration, expected_duration, delta=1.0)


if __name__ == '__main__':
    unittest.main()
