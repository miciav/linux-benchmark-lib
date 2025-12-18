"""System info collection tests."""

from __future__ import annotations

import types
from pathlib import Path

import pytest

import lb_runner.system_info as sysinfo
from lb_controller.services.run_service import RunService

pytestmark = [pytest.mark.runner]


def test_collect_system_info_writes_json_and_csv(monkeypatch, tmp_path):
    """Collector should emit both JSON and CSV and be summarizable."""
    # Stabilize environment-dependent bits
    monkeypatch.setattr(
        sysinfo,
        "_read_os_release",
        lambda: {"PRETTY_NAME": "TestOS", "VERSION": "1.0", "ID": "test"},
    )
    monkeypatch.setattr(
        sysinfo.platform,
        "uname",
        lambda: types.SimpleNamespace(
            node="node1",
            release="6.1.0",
            version="v1",
            machine="x86_64",
            system="Linux",
            processor="x86",
        ),
    )
    monkeypatch.setattr(sysinfo, "psutil", None)
    monkeypatch.setattr(
        sysinfo,
        "_json_output",
        lambda *args, **kwargs: {
            "blockdevices": [
                {
                    "name": "sda",
                    "size": 1073741824,
                    "rota": False,
                    "model": "DiskX",
                    "tran": "nvme",
                    "serial": "ABC123",
                }
            ]
        }
        if args and args[0] and args[0][0] == "lsblk"
        else None,
    )

    def _fake_run(cmd: list[str], timeout: float = 5.0) -> str:
        if cmd and cmd[0] == "lspci":
            return '0000:00:1f.2\t"Class"\t"Vendor"\t"Device"'
        if cmd and cmd[0] == "smartctl":
            return (
                "Device Model: Foo\n"
                "Serial Number: 123\n"
                "SMART overall-health self-assessment test result: PASSED"
            )
        return ""

    monkeypatch.setattr(sysinfo, "_run", _fake_run)
    monkeypatch.setattr(sysinfo.shutil, "which", lambda name: f"/usr/bin/{name}")

    info = sysinfo.collect_system_info()
    json_path = tmp_path / "system_info.json"
    csv_path = tmp_path / "system_info.csv"
    sysinfo.write_outputs(info, json_path, csv_path)

    assert json_path.exists()
    assert csv_path.exists()
    data = json_path.read_text()
    assert "TestOS" in data
    assert "DiskX" in data
    csv_data = csv_path.read_text()
    assert "category,name,value" in csv_data.splitlines()[0]

    # Summarize via RunService helper to ensure UI-friendly line
    svc = RunService(registry_factory=lambda: None)
    summary = svc._summarize_system_info(json_path)
    assert summary is not None
    assert "TestOS" in summary
    assert "CPU" in summary
    assert "RAM" in summary
