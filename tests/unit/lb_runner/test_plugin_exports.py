"""Tests for plugin-specific CSV exports."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from lb_plugins.api import GeekbenchPlugin, HPLPlugin, StreamPlugin, YabsPlugin

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]


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
            "generator_result": {
                "returncode": 0,
                "gflops": 42.5,
                "result_line": "WR00C2R4",
            },
        }
    ]

    paths = plugin.export_results_to_csv(results, output_dir, "run-1", "hpl")
    assert (output_dir / "hpl_plugin.csv") in paths
    df = pd.read_csv(output_dir / "hpl_plugin.csv")
    assert df.loc[0, "gflops"] == 42.5


def test_yabs_export_results_to_csv_parses_json_summary(tmp_path: Path) -> None:
    plugin = YabsPlugin()
    output_dir = tmp_path / "yabs"
    # `yabs.sh -j` ends its human-readable report with one JSON line.
    summary = {
        "version": "v2026-10-07",
        "os": {"arch": "aarch64", "distro": "Ubuntu 24.04.5 LTS", "vm": "KVM"},
        "cpu": {"model": "Cortex-X925\nBIOS virt-8.2", "cores": 4, "aes": True},
        "mem": {"ram": 8092000, "ram_units": "KiB"},
        "fio": [
            {
                "bs": "4k",
                "speed_r": 290662,
                "iops_r": 72665,
                "speed_w": 290467,
                "iops_w": 72616,
                "speed_rw": 581129,
                "iops_rw": 145281,
                "speed_units": "KBps",
            },
        ],
        "iperf": [
            {
                "mode": "IPv4",
                "provider": "Clouvider",
                "loc": "London, UK (10G)",
                "send": "931 Mbits/sec",
                "recv": "937 Mbits/sec",
                "latency": "37.3 ms",
            },
            {
                "mode": "IPv4",
                "provider": "Eranium",
                "loc": "Amsterdam, NL (100G)",
                "send": "150 Kbits/sec",
                "recv": "busy",
                "latency": "30.9 ms",
            },
        ],
    }
    sample_stdout = (
        "fio Disk Speed Tests (Mixed R/W 50/50) (Partition /dev/sda1):\n"
        "Read       | 283.85 MB/s  (69.2k) | 2.75 GB/s    (42.0k)\n\n"
        "YABS completed in 3 min 2 sec\n"
        # yabs does not escape values: a multi-line CPU model breaks the line.
        + json.dumps(summary).replace("\\n", "\n")
        + "\n"
    )
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
    assert df.loc[0, "cpu_model"] == "Cortex-X925\nBIOS virt-8.2"
    assert df.loc[0, "fio_4k_speed_r"] == 290662
    assert df.loc[0, "fio_4k_iops_rw"] == 145281
    iperf = pd.read_csv(output_dir / "yabs_iperf.csv")
    assert list(iperf["send_mbits"]) == [931.0, 0.15]
    assert iperf.loc[0, "recv_mbits"] == 937.0
    assert pd.isna(iperf.loc[1, "recv_mbits"])
    assert iperf.loc[1, "latency_ms"] == 30.9


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
