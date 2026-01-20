"""System info collection tests."""

from __future__ import annotations

import types

import pytest

from lb_runner.api import system_info_module as sysinfo, write_outputs
from lb_runner.services import system_info_collectors as collectors
from lb_app.api import summarize_system_info

pytestmark = [pytest.mark.unit_runner]

def test_system_info_to_dict_shape() -> None:
    info = sysinfo.SystemInfo(
        host="node1",
        timestamp="2024-01-01T00:00:00Z",
        os={"name": "TestOS"},
        kernel={"release": "6.1"},
        platform={"system": "Linux"},
        python={"version": "3.13"},
        cpu={"cores": 8},
        memory={"total": "1024"},
        disks=[sysinfo.DiskInfo(name="sda", size_bytes=1)],
        nics=[sysinfo.NicInfo(name="eth0", up=True)],
        pci=[sysinfo.PciDevice(slot="0000:00:1f.2", cls="Class")],
        smart=[sysinfo.SmartStatus(device="/dev/sda", health="PASSED")],
        modules=[sysinfo.KernelModule(name="kmod", size=1)],
        services=[sysinfo.SystemService(name="svc", state="running")],
        fingerprint="abc123",
    )

    payload = info.to_dict()
    expected_keys = {
        "host",
        "timestamp",
        "fingerprint",
        "os",
        "kernel",
        "platform",
        "python",
        "cpu",
        "memory",
        "disks",
        "nics",
        "pci",
        "smart",
        "modules",
        "services",
    }
    assert set(payload.keys()) == expected_keys
    assert payload["host"] == "node1"
    assert payload["fingerprint"] == "abc123"
    assert payload["disks"][0]["name"] == "sda"
    assert payload["nics"][0]["name"] == "eth0"
    assert payload["pci"][0]["slot"] == "0000:00:1f.2"
    assert payload["smart"][0]["device"] == "/dev/sda"
    assert payload["modules"][0]["name"] == "kmod"
    assert payload["services"][0]["name"] == "svc"


def test_system_info_to_csv_rows_shape() -> None:
    info = sysinfo.SystemInfo(
        host="node1",
        timestamp="2024-01-01T00:00:00Z",
        os={"name": "TestOS"},
        kernel={"release": "6.1"},
        platform={"system": "Linux"},
        python={"version": "3.13"},
        cpu={"cores": 8},
        memory={"total": "1024"},
        disks=[sysinfo.DiskInfo(name="sda", size_bytes=1)],
        nics=[sysinfo.NicInfo(name="eth0", up=True)],
        pci=[sysinfo.PciDevice(slot="0000:00:1f.2", cls="Class")],
        smart=[sysinfo.SmartStatus(device="/dev/sda", health="PASSED")],
        modules=[sysinfo.KernelModule(name="kmod", size=1)],
        services=[sysinfo.SystemService(name="svc", state="running")],
        fingerprint="abc123",
    )

    rows = info.to_csv_rows()
    assert rows
    assert all(set(row.keys()) == {"category", "name", "value"} for row in rows)
    assert len(rows) == 14
    assert any(row["category"] == "disk" and row["name"] == "sda" for row in rows)
    assert any(row["category"] == "nic" and row["name"] == "eth0" for row in rows)
    assert any(row["category"] == "pci" and row["name"] == "0000:00:1f.2" for row in rows)
    assert any(row["category"] == "smart" and row["name"] == "/dev/sda" for row in rows)
    assert any(row["category"] == "module" and row["name"] == "kmod" for row in rows)
    assert any(row["category"] == "service" and row["name"] == "svc" for row in rows)


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
    monkeypatch.setattr(collectors, "psutil", None)
    monkeypatch.setattr(
        collectors,
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

    monkeypatch.setattr(collectors, "_run", _fake_run)
    monkeypatch.setattr(collectors.shutil, "which", lambda name: f"/usr/bin/{name}")

    # Mock new collectors
    monkeypatch.setattr(
        sysinfo,
        "_collect_kernel_modules",
        lambda: [sysinfo.KernelModule("module_a", 1024)],
    )
    monkeypatch.setattr(
        sysinfo,
        "_collect_services",
        lambda: [sysinfo.SystemService("service_b", "running")],
    )

    info = sysinfo.collect_system_info()
    json_path = tmp_path / "system_info.json"
    csv_path = tmp_path / "system_info.csv"
    write_outputs(info, json_path, csv_path)

    assert json_path.exists()
    assert csv_path.exists()
    data = json_path.read_text()
    assert "TestOS" in data
    assert "DiskX" in data
    assert "module_a" in data
    assert "service_b" in data
    assert info.fingerprint != ""
    
    csv_data = csv_path.read_text()
    assert "category,name,value" in csv_data.splitlines()[0]
    assert "module_a" in csv_data
    assert "service_b" in csv_data

    summary = summarize_system_info(json_path)
    assert summary is not None
    assert "TestOS" in summary
    assert "CPU" in summary
    assert "RAM" in summary
