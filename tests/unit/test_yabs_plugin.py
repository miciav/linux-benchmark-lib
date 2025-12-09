import os
import subprocess
from pathlib import Path

import pytest

import lb_runner.plugins.yabs.plugin as yabs_mod

pytestmark = [pytest.mark.unit, pytest.mark.plugins]



def test_yabs_defaults():
    cfg = yabs_mod.YabsConfig()
    plugin = yabs_mod.PLUGIN
    assert plugin.name == "yabs"
    assert plugin.description
    gen = plugin.create_generator(cfg)
    assert isinstance(gen, yabs_mod.YabsGenerator)
    assert cfg.skip_geekbench is True
    assert cfg.skip_disk is False
    assert cfg.skip_network is False


def test_yabs_required_packages():
    plugin = yabs_mod.PLUGIN
    pkgs = plugin.get_required_apt_packages()
    for required in ("curl", "wget", "fio", "iperf3", "bc", "tar"):
        assert required in pkgs
    tools = plugin.get_required_local_tools()
    assert "bash" in tools


def test_yabs_paths_exist():
    plugin = yabs_mod.PLUGIN
    setup = plugin.get_ansible_setup_path()
    dockerfile = plugin.get_dockerfile_path()
    assert setup and setup.exists()
    assert dockerfile and dockerfile.exists()


def test_yabs_generator_builds_command(monkeypatch, tmp_path):
    cfg = yabs_mod.YabsConfig(skip_disk=True, skip_network=True, skip_geekbench=True, output_dir=tmp_path)
    gen = yabs_mod.YabsGenerator(cfg)

    calls = []

    def fake_run(cmd, check=False, capture_output=False, text=False, env=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    def fake_mkstemp(prefix, suffix):
        p = tmp_path / "yabs.sh"
        # Create file and return a valid fd
        fd = os.open(p, os.O_CREAT | os.O_RDWR)
        os.write(fd, b"#!/bin/bash\necho ok\n")
        return fd, str(p)

    monkeypatch.setattr(yabs_mod.tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(yabs_mod, "subprocess", yabs_mod.subprocess)
    monkeypatch.setattr(yabs_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(yabs_mod, "shutil", yabs_mod.shutil)
    monkeypatch.setattr(yabs_mod.shutil, "which", lambda _: "/usr/bin/tool")

    gen._run_command()
    # First call downloads script, second runs yabs
    assert len(calls) >= 2
    assert "-f" in calls[1] and "-i" in calls[1] and "-g" in calls[1]
