import json
import pytest
from pathlib import Path

from lb_runner.api import (
    BenchmarkConfig,
    MetricCollectorConfig,
    PerfConfig,
    WorkloadConfig,
)
from lb_plugins.api import StressNGConfig, DDConfig, FIOConfig


def create_reference_config() -> BenchmarkConfig:
    """Create a deterministic config for snapshotting."""
    stress_cfg = StressNGConfig(cpu_workers=2, cpu_method="matrixprod", timeout=20)
    # Set explicit paths to avoid random temp paths in snapshots
    dd_cfg = DDConfig(bs="4M", oflag="direct", of_path="/tmp/lb_test_dd.img")
    fio_cfg = FIOConfig(
        runtime=20,
        rw="randrw",
        bs="4k",
        iodepth=16,
        numjobs=1,
        size="256M",
        directory="/tmp/lb_test_fio",
    )

    return BenchmarkConfig(
        repetitions=1,
        test_duration_seconds=30,
        metrics_interval_seconds=1.0,
        warmup_seconds=2,
        cooldown_seconds=2,
        # Ensure consistent order for dicts if necessary, but pydantic dump usually handles it.
        # However, for snapshot stability, we rely on the JSON serializer's sort_keys.
        plugin_settings={
            "stress_ng": stress_cfg,
            "dd": dd_cfg,
            "fio": fio_cfg,
        },
        workloads={
            "stress_ng": WorkloadConfig(
                plugin="stress_ng", enabled=True, options=stress_cfg.model_dump()
            ),
        },
        collectors=MetricCollectorConfig(
            psutil_interval=1.0,
            cli_commands=["vmstat 1"],
            perf_config=PerfConfig(
                events=["cpu-cycles"],
                interval_ms=1000,
            ),
            enable_ebpf=False,
        ),
    )


@pytest.mark.inter_generic
def test_config_snapshot(request):
    """
    Verify that the BenchmarkConfig structure/defaults haven't changed unexpectedly.
    """
    cfg = create_reference_config()

    # Exclude dynamic paths like output_dir which might change per run/environment
    dump = cfg.model_dump(exclude={"output_dir", "report_dir", "data_export_dir"})

    # Serialize to JSON with sorted keys for stability
    actual_json = json.dumps(dump, indent=2, sort_keys=True)

    snapshot_path = (
        Path(__file__).parent.parent / "snapshots" / "benchmark_config_snapshot.json"
    )

    # If snapshot doesn't exist, create it (First run)
    if not snapshot_path.exists():
        snapshot_path.write_text(actual_json)
        pytest.fail(f"Snapshot created at {snapshot_path}. Run again to verify.")

    expected_json = snapshot_path.read_text()

    assert actual_json == expected_json, "Configuration structure changed! Check diff."
