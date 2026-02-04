#!/usr/bin/env python3
"""Quick local-run example using the public runner API."""

from pathlib import Path

from lb_common.api import configure_logging
from lb_plugins.api import (
    DDConfig,
    FIOConfig,
    PluginRegistry,
    StressNGConfig,
    create_registry,
)
from lb_runner.api import (
    BenchmarkConfig,
    LocalRunner,
    MetricCollectorConfig,
    PerfConfig,
    WorkloadConfig,
)


def setup_logging() -> None:
    """Set up simple console+file logging for the demo run."""
    configure_logging(level="INFO", log_file="benchmark.log", force=True)


def create_custom_config() -> BenchmarkConfig:
    """Create a small local config with one enabled workload."""
    stress_cfg = StressNGConfig(cpu_workers=2, cpu_method="matrixprod", timeout=20)
    dd_cfg = DDConfig(bs="4M", oflag="direct")
    fio_cfg = FIOConfig(
        runtime=20,
        rw="randrw",
        bs="4k",
        iodepth=16,
        numjobs=1,
        size="256M",
    )

    return BenchmarkConfig(
        repetitions=1,
        test_duration_seconds=30,
        metrics_interval_seconds=1.0,
        warmup_seconds=2,
        cooldown_seconds=2,
        plugin_settings={
            "stress_ng": stress_cfg,
            "dd": dd_cfg,
            "fio": fio_cfg,
        },
        workloads={
            "stress_ng": WorkloadConfig(
                plugin="stress_ng",
                enabled=True,
                options=stress_cfg.model_dump(),
            ),
            "dd": WorkloadConfig(
                plugin="dd",
                enabled=False,
                options=dd_cfg.model_dump(),
            ),
            "fio": WorkloadConfig(
                plugin="fio",
                enabled=False,
                options=fio_cfg.model_dump(),
            ),
        },
        collectors=MetricCollectorConfig(
            psutil_interval=1.0,
            cli_commands=["vmstat 1", "iostat -x 1"],
            perf_config=PerfConfig(
                events=["cpu-cycles", "instructions", "cache-misses"],
                interval_ms=1000,
            ),
            enable_ebpf=False,  # eBPF requires root and BCC tools
        ),
    )


def run_single_benchmark(
    config: BenchmarkConfig, test_type: str, registry: PluginRegistry
) -> None:
    """Run one workload with the local runner and print status."""
    print(f"\n{'='*60}")
    print(f"Running {test_type} benchmark")
    print(f"{'='*60}\n")

    runner = LocalRunner(config, registry=registry)
    system_info = runner.collect_system_info()
    print(
        "System Info:",
        system_info["platform"],
        "Python",
        system_info["python"]["version"],
    )

    try:
        runner.run_benchmark(test_type)
        print(f"\n✅ {test_type} benchmark completed successfully!")
    except Exception as exc:  # pragma: no cover - demo output
        print(f"\n❌ {test_type} benchmark failed: {exc}")


def main() -> None:
    setup_logging()
    config = create_custom_config()
    config.ensure_output_dirs()

    config.save(Path("example_config.json"))
    print("Configuration saved to example_config.json")

    registry = create_registry()
    run_single_benchmark(config, "stress_ng", registry)

    print(f"\nOutputs in: {config.output_dir.resolve()}")
    print(f"Reports in: {config.report_dir.resolve()}")


if __name__ == "__main__":
    main()
