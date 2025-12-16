"""Tests for plugin-specific CSV exports."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from lb_runner.plugins.geekbench.plugin import GeekbenchPlugin
from lb_runner.plugins.hpl.plugin import HPLPlugin
from lb_runner.plugins.stream.plugin import StreamPlugin
from lb_runner.plugins.yabs.plugin import YabsPlugin

pytestmark = [pytest.mark.unit, pytest.mark.plugins]


def test_geekbench_export_results_to_csv_parses_json(tmp_path: Path) -> None:
    plugin = GeekbenchPlugin()
    output_dir = tmp_path / "geekbench"
    output_dir.mkdir()

    sample_json = {
        "scores": {"single_core_score": 1234, "multi_core_score": 5678},
        "geekbench_version": "6.3.0",
        "workloads": [
            {"name": "AES-XTS", "score": 100},
            {"name": "Blur", "score": 200},
        ],
    }
    json_path = output_dir / "geekbench_result.json"
    json_path.write_text(json.dumps(sample_json))

    results = [
        {
            "repetition": 1,
            "duration_seconds": 10.0,
            "success": True,
            "generator_result": {"returncode": 0, "json_result": str(json_path)},
        }
    ]

    paths = plugin.export_results_to_csv(results, output_dir, "run-1", "geekbench")
    assert (output_dir / "geekbench_plugin.csv") in paths
    df = pd.read_csv(output_dir / "geekbench_plugin.csv")
    assert df.loc[0, "single_core_score"] == 1234
    assert df.loc[0, "multi_core_score"] == 5678
    assert df.loc[0, "geekbench_version"] == "6.3.0"

    subtests_path = output_dir / "geekbench_subtests.csv"
    assert subtests_path.exists()
    sub_df = pd.read_csv(subtests_path)
    assert set(sub_df["subtest"]) == {"AES-XTS", "Blur"}


def test_hpl_export_results_to_csv_writes_gflops(tmp_path: Path) -> None:
    plugin = HPLPlugin()
    output_dir = tmp_path / "hpl"

    results = [
        {
            "repetition": 1,
            "duration_seconds": 30.0,
            "success": True,
            "generator_result": {"returncode": 0, "gflops": 42.5, "result_line": "WR00C2R4"},
        }
    ]

    paths = plugin.export_results_to_csv(results, output_dir, "run-1", "hpl")
    assert (output_dir / "hpl_plugin.csv") in paths
    df = pd.read_csv(output_dir / "hpl_plugin.csv")
    assert df.loc[0, "gflops"] == 42.5


def test_yabs_export_results_to_csv_parses_stdout(tmp_path: Path) -> None:
    plugin = YabsPlugin()
    output_dir = tmp_path / "yabs"
    sample_stdout = """
CPU Model: Intel(R) Xeon(R)
Architecture: x86_64
Virtualization: KVM
Events per second: 1234.56
total time: 10.0s
Disk Speed:
Read: 789.0 MB/s
Write: 456.0 MB/s
iperf3 Network Speed:
Download: 900.1 Mbits/sec
Upload: 800.2 Mbits/sec
"""
    results = [
        {
            "repetition": 1,
            "duration_seconds": 12.0,
            "success": True,
            "generator_result": {"returncode": 0, "stdout": sample_stdout},
        }
    ]
    paths = plugin.export_results_to_csv(results, output_dir, "run-1", "yabs")
    assert (output_dir / "yabs_plugin.csv") in paths
    df = pd.read_csv(output_dir / "yabs_plugin.csv")
    assert df.loc[0, "cpu_events_per_sec"] == 1234.56
    assert df.loc[0, "disk_read_mb_s"] == 789.0
    assert df.loc[0, "net_download_mbits"] == 900.1


def test_stream_export_results_to_csv_writes_triad(tmp_path: Path) -> None:
    plugin = StreamPlugin()
    output_dir = tmp_path / "stream"

    results = [
        {
            "repetition": 1,
            "duration_seconds": 3.0,
            "success": True,
            "generator_result": {
                "returncode": 0,
                "stream_array_size": 10_000_000,
                "ntimes": 10,
                "threads": 4,
                "triad_best_rate_mb_s": 9999.9,
                "validated": True,
            },
        }
    ]

    paths = plugin.export_results_to_csv(results, output_dir, "run-1", "stream")
    assert (output_dir / "stream_plugin.csv") in paths
    df = pd.read_csv(output_dir / "stream_plugin.csv")
    assert df.loc[0, "triad_best_rate_mb_s"] == 9999.9
