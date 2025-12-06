#!/usr/bin/env python3
"""
Example script demonstrating the usage of the Linux Benchmark Library.

This script shows how to configure and run various benchmark tests.
"""

import logging
from pathlib import Path

from dataclasses import asdict

from lb_runner.benchmark_config import (
    BenchmarkConfig,
    MetricCollectorConfig,
    PerfConfig,
    WorkloadConfig,
)
from lb_runner.local_runner import LocalRunner
from lb_ui.reporter import Reporter
from lb_runner.plugin_system.builtin import builtin_plugins
from lb_runner.plugin_system.registry import PluginRegistry
from lb_runner.plugins.dd.plugin import DDConfig
from lb_runner.plugins.stress_ng.plugin import StressNGConfig
from lb_runner.plugins.fio.plugin import FIOConfig


def setup_logging():
    """Set up logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('benchmark.log'),
            logging.StreamHandler()
        ]
    )


def create_custom_config() -> BenchmarkConfig:
    """Create a custom benchmark configuration."""
    stress_cfg = StressNGConfig(
        cpu_workers=2,
        cpu_method="matrixprod",
        vm_workers=1,
        vm_bytes="512M",
        io_workers=1,
        timeout=30,
    )
    dd_cfg = DDConfig(
        bs="4M",
        oflag="direct",
    )
    fio_cfg = FIOConfig(
        runtime=30,
        rw="randrw",
        bs="4k",
        iodepth=32,
        numjobs=2,
        size="512M",
    )

    config = BenchmarkConfig(
        repetitions=3,
        test_duration_seconds=30,  # Shorter duration for example
        metrics_interval_seconds=1.0,
        warmup_seconds=5,
        cooldown_seconds=5,
        plugin_settings={
            "stress_ng": stress_cfg,
            "dd": dd_cfg,
            "fio": fio_cfg,
        },
        workloads={
            "stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True, options=asdict(stress_cfg)),
            "dd": WorkloadConfig(plugin="dd", enabled=False, options=asdict(dd_cfg)),
            "fio": WorkloadConfig(plugin="fio", enabled=False, options=asdict(fio_cfg)),
        },
        collectors=MetricCollectorConfig(
            psutil_interval=1.0,
            cli_commands=["vmstat 1", "iostat -x 1"],
            perf_config=PerfConfig(
                events=["cpu-cycles", "instructions", "cache-misses"],
                interval_ms=1000,
            ),
            enable_ebpf=False,  # Requires root and BCC tools
        ),
    )
    return config


def run_single_benchmark(
    config: BenchmarkConfig,
    test_type: str,
    registry: PluginRegistry,
) -> None:
    """Run a single benchmark test."""
    print(f"\n{'='*60}")
    print(f"Running {test_type} benchmark")
    print(f"{'='*60}\n")
    
    runner = LocalRunner(config, registry=registry)
    
    # Collect system information
    system_info = runner.collect_system_info()
    print("System Information:")
    print(f"  Platform: {system_info['platform']['system']} {system_info['platform']['release']}")
    print(f"  Machine: {system_info['platform']['machine']}")
    print(f"  Python: {system_info['python']['version']}\n")
    
    # Run the benchmark
    try:
        runner.run_benchmark(test_type)
        print(f"\n✅ {test_type} benchmark completed successfully!")
    except Exception as e:
        print(f"\n❌ {test_type} benchmark failed: {e}")


def generate_reports(config: BenchmarkConfig):
    """Generate reports for completed benchmarks."""
    print(f"\n{'='*60}")
    print("Generating Reports")
    print(f"{'='*60}\n")
    
    reporter = Reporter(config.report_dir)
    
    # Check for aggregated data files
    for csv_file in config.data_export_dir.glob("*_aggregated.csv"):
        test_name = csv_file.stem.replace("_aggregated", "")
        
        try:
            import pandas as pd
            df = pd.read_csv(csv_file, index_col=0)
            
            # Generate text report
            reporter.generate_text_report(df, test_name)
            
            # Generate graphical report
            reporter.generate_graphical_report(df, test_name)
            
            print(f"✅ Generated reports for {test_name}")
            
        except Exception as e:
            print(f"❌ Failed to generate reports for {test_name}: {e}")


def main():
    """Main function."""
    # Set up logging
    setup_logging()
    
    # Create configuration
    config = create_custom_config()
    
    # Save configuration for reference
    config.save(Path("example_config.json"))
    print(f"Configuration saved to example_config.json")
    
    # Run individual benchmarks
    # Note: Some tests may require specific setup:
    # - stress_ng: Should work out of the box if installed
    # - dd: Should work, but be careful with disk space and throughput settings
    # - fio: Should work if installed
    
    # Example: Run only stress-ng benchmark
    registry = PluginRegistry(builtin_plugins())
    run_single_benchmark(config, "stress_ng", registry)
    
    # Uncomment to run other benchmarks:
    # run_single_benchmark(config, "dd")
    # run_single_benchmark(config, "fio")
    
    # Generate reports
    generate_reports(config)
    
    print(f"\n{'='*60}")
    print("Benchmark session completed!")
    print(f"Results saved to: {config.output_dir}")
    print(f"Reports saved to: {config.report_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
