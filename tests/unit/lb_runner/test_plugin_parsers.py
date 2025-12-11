"""Lightweight parser tests for plugins using fixture-like data."""

import json
from pathlib import Path

import pytest

from lb_runner.plugins.dd.plugin import DDConfig, DDPlugin
from lb_runner.plugins.fio.plugin import FIOConfig, FIOPlugin
from lb_runner.plugins.hpl.plugin import HPLConfig, HPLPlugin


pytestmark = pytest.mark.unit


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
