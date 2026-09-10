"""Real integration tests that actually execute benchmarks.

These tests run actual benchmarks with minimal parameters to verify
the entire system works end-to-end.
"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import pytest

from lb_plugins.api import PluginRegistry, StressNGConfig, builtin_plugins
from lb_runner.api import (
    BenchmarkConfig,
    LocalRunner,
    MetricCollectorConfig,
    WorkloadConfig,
)

pytestmark = [pytest.mark.inter_e2e, pytest.mark.slow]


class TestRealBenchmarkIntegration(unittest.TestCase):
    """Integration tests that run actual benchmarks."""

    def setUp(self):
        """Set up temporary directories for test outputs."""
        self.temp_dir = tempfile.mkdtemp(prefix="benchmark_test_")
        self.temp_path = Path(self.temp_dir)
        self.registry = PluginRegistry(builtin_plugins())

    def tearDown(self):
        """Clean up temporary directories."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @unittest.skipUnless(
        shutil.which("stress-ng") is not None, "stress-ng not installed"
    )
    def test_minimal_stress_ng_benchmark(self):
        """Test a minimal stress-ng benchmark execution."""
        # Create a minimal configuration
        stress_cfg = StressNGConfig(
            cpu_workers=1,  # Minimal workers
            vm_workers=0,  # Disable VM workers
            io_workers=0,  # Disable IO workers
            timeout=2,
        )
        config = BenchmarkConfig(
            repetitions=1,
            test_duration_seconds=2,  # Very short duration
            metrics_interval_seconds=0.5,
            warmup_seconds=0,
            cooldown_seconds=0,
            output_dir=self.temp_path / "results",
            report_dir=self.temp_path / "reports",
            data_export_dir=self.temp_path / "exports",
            plugin_settings={"stress_ng": stress_cfg},
            workloads={
                "stress_ng": WorkloadConfig(
                    plugin="stress_ng",
                    options=stress_cfg.model_dump(mode="json"),
                )
            },
            collectors=MetricCollectorConfig(
                psutil_interval=0.5,
                cli_commands=[],  # No CLI commands for speed
                enable_ebpf=False,
            ),
        )

        # Create and run local controller
        runner = LocalRunner(config, registry=self.registry)

        # Collect system info
        system_info = runner.collect_system_info()
        assert system_info is not None
        assert "platform" in system_info
        assert "python" in system_info

        # Run the benchmark
        start_time = time.time()
        runner.run_benchmark("stress_ng")
        end_time = time.time()
        run_id = getattr(runner, "_current_run_id", None)
        output_root = config.output_dir / run_id if run_id else config.output_dir
        workload_dir = output_root / "stress_ng"
        # Verify execution time is reasonable
        execution_time = end_time - start_time
        assert execution_time < 10  # Should complete within 10 seconds

        # Verify output files were created
        results_file = workload_dir / "stress_ng_results.json"
        assert results_file.exists(), f"Results file not found: {results_file}"

        # Load and verify results
        with Path(results_file).open() as f:
            results = json.load(f)

        assert isinstance(results, list)
        assert len(results) == 1  # One repetition

        result = results[0]
        assert result["test_name"] == "stress_ng"
        assert result["repetition"] == 1
        assert "start_time" in result
        assert "end_time" in result
        assert "duration_seconds" in result
        assert "generator_result" in result
        assert "metrics" in result

        # Verify metrics were collected
        assert "PSUtilCollector" in result["metrics"]
        psutil_metrics = result["metrics"]["PSUtilCollector"]
        assert isinstance(psutil_metrics, list)
        assert len(psutil_metrics) > 0

        # Verify metric data structure
        for metric in psutil_metrics:
            assert "timestamp" in metric
            assert "cpu_percent" in metric
            assert "memory_usage" in metric

        # Aggregated CSVs are no longer produced by the runner; analytics runs via UI/CLI.

        # Verify collector raw data files (allow nested paths or new naming)
        collector_files = list(workload_dir.rglob("*.csv"))
        assert len(collector_files) > 0, "No collector CSV files found"

    def test_system_info_collection(self):
        """Test system information collection."""
        config = BenchmarkConfig(
            output_dir=self.temp_path / "results",
            report_dir=self.temp_path / "reports",
            data_export_dir=self.temp_path / "exports",
        )

        runner = LocalRunner(config, registry=self.registry)
        system_info = runner.collect_system_info()

        # Verify basic system info
        assert "timestamp" in system_info
        assert "platform" in system_info
        assert "python" in system_info

        platform_info = system_info["platform"]
        assert "system" in platform_info
        assert "machine" in platform_info
        assert "release" in platform_info

        python_info = system_info["python"]
        assert "version" in python_info
        assert "implementation" in python_info

    @unittest.skipUnless(
        shutil.which("stress-ng") is not None, "stress-ng not installed"
    )
    def test_stress_ng_with_multiple_metrics(self):
        """Test stress-ng with multiple metric collectors enabled."""
        stress_cfg = StressNGConfig(cpu_workers=2, cpu_method="matrixprod", timeout=3)
        config = BenchmarkConfig(
            repetitions=1,
            test_duration_seconds=3,
            metrics_interval_seconds=1.0,
            warmup_seconds=0,
            cooldown_seconds=0,
            output_dir=self.temp_path / "results",
            report_dir=self.temp_path / "reports",
            data_export_dir=self.temp_path / "exports",
            plugin_settings={"stress_ng": stress_cfg},
            workloads={
                "stress_ng": WorkloadConfig(
                    plugin="stress_ng",
                    options=stress_cfg.model_dump(mode="json"),
                )
            },
            collectors=MetricCollectorConfig(
                psutil_interval=1.0,
                cli_commands=[],  # Disable CLI commands to avoid jc parser issues
                enable_ebpf=False,
            ),
        )

        runner = LocalRunner(config, registry=self.registry)
        runner.run_benchmark("stress_ng")
        run_id = getattr(runner, "_current_run_id", None)
        output_root = config.output_dir / run_id if run_id else config.output_dir
        workload_dir = output_root / "stress_ng"

        # Load results
        results_file = workload_dir / "stress_ng_results.json"
        with Path(results_file).open() as f:
            results = json.load(f)

        result = results[0]

        # Verify PSUtil collector ran
        assert "PSUtilCollector" in result["metrics"]

        # Verify timing (duration is only the test execution time, not warmup/cooldown)
        duration = result["duration_seconds"]
        expected_duration = config.test_duration_seconds
        # Allow modest overhead for process startup/teardown and collector timing
        assert duration >= expected_duration
        assert duration <= expected_duration + 3.0


if __name__ == "__main__":
    unittest.main()
