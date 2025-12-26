import os
import shutil
import subprocess
import tempfile

import pytest

from lb_plugins.api import YabsConfig, YabsGenerator, YabsPlugin

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]



def test_yabs_defaults():
    cfg = YabsConfig()
    plugin = YabsPlugin()
    assert plugin.name == "yabs"
    assert plugin.description
    gen = plugin.create_generator(cfg)
    assert isinstance(gen, YabsGenerator)
    assert cfg.skip_geekbench is True
    assert cfg.skip_disk is False
    assert cfg.skip_network is False


def test_yabs_required_packages():
    plugin = YabsPlugin()
    pkgs = plugin.get_required_apt_packages()
    for required in ("curl", "wget", "fio", "iperf3", "bc", "tar"):
        assert required in pkgs
    tools = plugin.get_required_local_tools()
    assert "bash" in tools


def test_yabs_paths_exist():
    plugin = YabsPlugin()
    setup = plugin.get_ansible_setup_path()
    assert setup and setup.exists()


def test_yabs_generator_builds_command(monkeypatch, tmp_path):
    cfg = YabsConfig(skip_disk=True, skip_network=True, skip_geekbench=True, output_dir=tmp_path)
    gen = YabsGenerator(cfg)

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    def fake_mkstemp(*_args, **_kwargs):
        p = tmp_path / "yabs.sh"
        # Create file and return a valid fd
        fd = os.open(p, os.O_CREAT | os.O_RDWR)
        os.write(fd, b"#!/bin/bash\necho ok\n")
        return fd, str(p)

    monkeypatch.setattr(tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/tool")

    gen._run_command()
    # First call downloads script, second runs yabs
    assert len(calls) >= 2
    assert "-f" in calls[1] and "-i" in calls[1] and "-g" in calls[1]
