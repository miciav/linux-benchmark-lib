"""Lightweight parser tests for plugins using fixture-like data."""

import json
from pathlib import Path

import pytest

from lb_plugins.plugins.dd.plugin import DDConfig, DDPlugin
from lb_plugins.plugins.fio.plugin import FIOConfig, FIOPlugin
from lb_plugins.plugins.hpl.plugin import HPLConfig, HPLPlugin
from lb_plugins.plugins.stream.plugin import StreamConfig, StreamPlugin


pytestmark = pytest.mark.unit_runner


def test_dd_builds_command_and_handles_options(tmp_path):
    plugin = DDPlugin()
    cfg = DDConfig(
        if_path="/dev/zero",
        of_path=str(tmp_path / "out"),
        bs="2M",
        count=1,
        conv="fdatasync",
        oflag="direct",
    )
    gen = plugin.create_generator(cfg)
    cmd = gen._build_command()  # type: ignore[attr-defined]
    assert "dd" in cmd[0]
    joined = " ".join(cmd)
    assert "if=/dev/zero" in joined
    assert "of=" in joined
    assert "bs=2M" in joined
    assert "count=1" in joined
    assert any(part.startswith("status=") for part in cmd)


def test_fio_parses_sample_json():
    sample = {
        "jobs": [
            {
                "read": {"iops": 1000, "bw": 2048},
                "write": {"iops": 500, "bw": 1024},
            }
        ]
    }
    plugin = FIOPlugin()
    gen = plugin.create_generator(FIOConfig())
    metrics = gen._parse_json_output(json.dumps(sample))  # type: ignore[attr-defined]
    assert metrics["read_iops"] == 1000
    assert metrics["write_iops"] == 500


def test_hpl_parses_output_paths(tmp_path):
    plugin = HPLPlugin()
    cfg = HPLConfig(mpi_launcher="fork", workspace_dir=str(tmp_path))
    gen = plugin.create_generator(cfg)

    # Local fork launcher should map to isolated plm flags
    assert gen._launcher_flags() == ["--mca", "plm", "isolated"]

    cfg_ssh = HPLConfig(mpi_launcher="ssh", workspace_dir=str(tmp_path))
    gen_ssh = plugin.create_generator(cfg_ssh)
    flags = gen_ssh._launcher_flags()
    assert flags[:2] == ["--mca", "plm_rsh_agent"]
    assert "ssh" in flags


def test_hpl_parses_stdout_metrics(tmp_path):
    plugin = HPLPlugin()
    gen = plugin.create_generator(HPLConfig(mpi_launcher="fork", workspace_dir=str(tmp_path)))
    sample = """
T/V                N    NB     P     Q               Time                 Gflops
--------------------------------------------------------------------------------
WR00C2R4        10000   256     1     1            12.34              54.321
||Ax-b||_oo / ( eps * ( ||A||_oo * ||x||_oo + ||b||_oo ) * N ) = 0.1234
PASSED
"""
    metrics = gen._parse_output(sample)  # type: ignore[attr-defined]
    assert metrics["gflops"] == 54.321
    assert metrics["time_seconds"] == 12.34
    assert metrics["n"] == 10000
    assert metrics["nb"] == 256
    assert metrics["p"] == 1
    assert metrics["q"] == 1
    assert metrics["residual"] == 0.1234
    assert metrics["residual_passed"] is True


def test_stream_parses_stdout_metrics() -> None:
    plugin = StreamPlugin()
    gen = plugin.create_generator(StreamConfig())
    sample = """
-------------------------------------------------------------
STREAM version $Revision: 5.10 $
-------------------------------------------------------------
Function    Best Rate MB/s  Avg time     Min time     Max time
Copy:       12345.6         0.0012       0.0011       0.0013
Scale:      23456.7         0.0022       0.0021       0.0023
Add:        34567.8         0.0032       0.0031       0.0033
Triad:      45678.9         0.0042       0.0041       0.0043
Solution Validates: avg error less than 1.000000e-13 on all three arrays
"""
    metrics = gen._parse_output(sample)  # type: ignore[attr-defined]
    assert metrics["copy_best_rate_mb_s"] == 12345.6
    assert metrics["triad_best_rate_mb_s"] == 45678.9
    assert metrics["validated"] is True
