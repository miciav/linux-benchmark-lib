#!/usr/bin/env python3
"""
Example script demonstrating the usage of the Linux Benchmark Library.

This script shows how to configure and run various benchmark tests.
"""

import logging
from pathlib import Path

from benchmark_config import (
    BenchmarkConfig,
    StressNGConfig,
    IPerf3Config,
    DDConfig,
    FIOConfig,
    MetricCollectorConfig,
    PerfConfig
)
from orchestrator import Orchestrator
from reporter import Reporter


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
    return BenchmarkConfig(
        # Test execution parameters
        repetitions=3,
        test_duration_seconds=30,  # Shorter duration for example
        metrics_interval_seconds=1.0,
        warmup_seconds=5,
        cooldown_seconds=5,
        
        # Custom stress-ng configuration
        stress_ng=StressNGConfig(
            cpu_workers=2,
            cpu_method="matrixprod",
            vm_workers=1,
            vm_bytes="512M",
            io_workers=1,
            timeout=30
        ),
        
        # Custom iperf3 configuration
        iperf3=IPerf3Config(
            server_host="localhost",  # Requires iperf3 server running
            parallel=2,
            time=30,
            protocol="tcp"
        ),
        
        # Custom dd configuration
        dd=DDConfig(
            bs="4M",
            count=256,  # 1GB total
            oflag="direct"
        ),
        
        # Custom fio configuration
        fio=FIOConfig(
            runtime=30,
            rw="randrw",
            bs="4k",
            iodepth=32,
            numjobs=2,
            size="512M"
        ),
        
        # Metric collector configuration
        collectors=MetricCollectorConfig(
            psutil_interval=1.0,
            cli_commands=["vmstat 1", "iostat -x 1"],
            perf_config=PerfConfig(
                events=["cpu-cycles", "instructions", "cache-misses"],
                interval_ms=1000
            ),
            enable_ebpf=False  # Requires root and BCC tools
        )
    )


def run_single_benchmark(config: BenchmarkConfig, test_type: str):
    """Run a single benchmark test."""
    print(f"\n{'='*60}")
    print(f"Running {test_type} benchmark")
    print(f"{'='*60}\n")
    
    orchestrator = Orchestrator(config)
    
    # Collect system information
    system_info = orchestrator.collect_system_info()
    print("System Information:")
    print(f"  Platform: {system_info['platform']['system']} {system_info['platform']['release']}")
    print(f"  Machine: {system_info['platform']['machine']}")
    print(f"  Python: {system_info['python']['version']}\n")
    
    # Run the benchmark
    try:
        orchestrator.run_benchmark(test_type)
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
    # - iperf3: Requires an iperf3 server running
    # - dd: Should work, but be careful with disk space
    # - fio: Should work if installed
    
    # Example: Run only stress-ng benchmark
    run_single_benchmark(config, "stress_ng")
    
    # Uncomment to run other benchmarks:
    # run_single_benchmark(config, "dd")
    # run_single_benchmark(config, "fio")
    # run_single_benchmark(config, "iperf3")  # Requires iperf3 server
    
    # Generate reports
    generate_reports(config)
    
    print(f"\n{'='*60}")
    print("Benchmark session completed!")
    print(f"Results saved to: {config.output_dir}")
    print(f"Reports saved to: {config.report_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
