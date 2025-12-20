"""System information collection utilities.

Collects host static data (OS, kernel, CPU, memory, disks, network) and optional
hardware details (PCI, SMART). Designed to run both locally and on remote hosts
provisioned by Ansible.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - defensive
    psutil = None


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    """Run a command safely, returning stdout or empty string on failure."""
    try:
        result = subprocess.run(
            cmd, check=False, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception:
        return ""


def _json_output(cmd: list[str], timeout: float = 5.0) -> Any:
    """Run a command expected to emit JSON; return parsed object or None."""
    raw = _run(cmd, timeout=timeout)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _read_os_release() -> dict[str, str]:
    """Parse /etc/os-release when available."""
    data: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.exists():
        return data
    for line in path.read_text().splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        data[key.strip()] = val.strip().strip('"')
    return data


@dataclass
class DiskInfo:
    name: str
    size_bytes: int | None = None
    rotational: bool | None = None
    model: str | None = None
    transport: str | None = None
    serial: str | None = None


@dataclass
class NicInfo:
    name: str
    up: bool | None = None
    speed_mbps: int | None = None
    mac: str | None = None


@dataclass
class PciDevice:
    slot: str
    cls: str | None = None
    vendor: str | None = None
    device: str | None = None


@dataclass
class SmartStatus:
    device: str
    model: str | None = None
    serial: str | None = None
    health: str | None = None


@dataclass
class SystemInfo:
    host: str
    timestamp: str
    os: dict[str, Any]
    kernel: dict[str, Any]
    platform: dict[str, Any]
    python: dict[str, Any]
    cpu: dict[str, Any]
    memory: dict[str, Any]
    disks: list[DiskInfo] = field(default_factory=list)
    nics: list[NicInfo] = field(default_factory=list)
    pci: list[PciDevice] = field(default_factory=list)
    smart: list[SmartStatus] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "timestamp": self.timestamp,
            "os": self.os,
            "kernel": self.kernel,
            "platform": self.platform,
            "python": self.python,
            "cpu": self.cpu,
            "memory": self.memory,
            "disks": [asdict(d) for d in self.disks],
            "nics": [asdict(n) for n in self.nics],
            "pci": [asdict(p) for p in self.pci],
            "smart": [asdict(s) for s in self.smart],
        }

    def to_csv_rows(self) -> list[dict[str, str]]:
        """Flatten into key/value rows suitable for CSV."""
        rows: list[dict[str, str]] = []

        def add(category: str, name: str, value: Any) -> None:
            rows.append({"category": category, "name": name, "value": str(value)})

        # Basic sections
        add("meta", "timestamp", self.timestamp)
        for k, v in self.platform.items():
            add("platform", k, v)
        for k, v in self.python.items():
            add("python", k, v)
        for k, v in self.os.items():
            add("os", k, v)
        for k, v in self.kernel.items():
            add("kernel", k, v)
        for k, v in self.cpu.items():
            add("cpu", k, v)
        for k, v in self.memory.items():
            add("memory", k, v)

        for disk in self.disks:
            add("disk", disk.name, json.dumps({k: v for k, v in asdict(disk).items() if v is not None}))
        for nic in self.nics:
            add("nic", nic.name, json.dumps({k: v for k, v in asdict(nic).items() if v is not None}))
        for dev in self.pci:
            add("pci", dev.slot, json.dumps({k: v for k, v in asdict(dev).items() if v is not None}))
        for sm in self.smart:
            add("smart", sm.device, json.dumps({k: v for k, v in asdict(sm).items() if v is not None}))
        return rows


def _collect_cpu() -> dict[str, Any]:
    info: dict[str, Any] = {}

    lscpu_json = _json_output(["lscpu", "-J"])
    if isinstance(lscpu_json, dict) and "lscpu" in lscpu_json:
        for entry in lscpu_json["lscpu"]:
            if not isinstance(entry, dict):
                continue
            field = entry.get("field", "").strip(": ")
            value = entry.get("data")
            if field and value is not None:
                info[field.lower().replace(" ", "_")] = value
    else:
        # Fallback to /proc/cpuinfo
        cpuinfo = _run(["cat", "/proc/cpuinfo"])
        if cpuinfo:
            for line in cpuinfo.splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                key = k.strip().lower().replace(" ", "_")
                if key in ("model_name", "vendor_id", "cpu_mhz", "cpu_cores"):
                    info.setdefault(key, v.strip())

    if psutil:
        info["logical_cpus"] = psutil.cpu_count(logical=True)
        info["physical_cpus"] = psutil.cpu_count(logical=False)
        try:
            freq = psutil.cpu_freq()
            if freq:
                info["freq_current_mhz"] = freq.current
                info["freq_min_mhz"] = freq.min
                info["freq_max_mhz"] = freq.max
        except Exception:
            pass
    return info


def _collect_memory() -> dict[str, Any]:
    info: dict[str, Any] = {}
    if psutil:
        try:
            vm = psutil.virtual_memory()
            info["total_bytes"] = vm.total
            info["available_bytes"] = vm.available
            swap = psutil.swap_memory()
            info["swap_total_bytes"] = swap.total
        except Exception:
            pass
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text().splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = k.strip().lower()
            info.setdefault(key, v.strip())
    return info


def _collect_disks() -> list[DiskInfo]:
    disks: list[DiskInfo] = []
    lsblk = _json_output(["lsblk", "-J", "-O"])
    if lsblk and isinstance(lsblk, dict):
        for block in lsblk.get("blockdevices", []):
            name = block.get("name")
            if not name:
                continue
            size = block.get("size")
            model = block.get("model")
            rota = block.get("rota")
            transport = block.get("tran")
            serial = block.get("serial")
            disks.append(
                DiskInfo(
                    name=str(name),
                    size_bytes=int(size) if isinstance(size, (int, float, str)) and str(size).isdigit() else None,
                    rotational=bool(rota) if rota is not None else None,
                    model=model,
                    transport=transport,
                    serial=serial,
                )
            )
    else:
        # Minimal fallback: list block devices in /sys/block when present
        sys_block = Path("/sys/block")
        if sys_block.exists():
            for entry in sys_block.iterdir():
                if not entry.is_dir():
                    continue
                rota_path = entry / "queue" / "rotational"
                rota = None
                if rota_path.exists():
                    try:
                        rota = rota_path.read_text().strip() == "1"
                    except Exception:
                        pass
                disks.append(DiskInfo(name=entry.name, rotational=rota))
    return disks


def _collect_nics() -> list[NicInfo]:
    nics: list[NicInfo] = []
    if psutil:
        try:
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            for name, st in stats.items():
                if name == "lo":
                    continue
                mac = None
                for addr in addrs.get(name, []):
                    if getattr(addr, "family", None) == getattr(getattr(psutil, "AF_LINK", None), "__class__", None):
                        mac = addr.address
                nics.append(
                    NicInfo(
                        name=name,
                        up=st.isup,
                        speed_mbps=st.speed if st.speed and st.speed > 0 else None,
                        mac=mac,
                    )
                )
        except Exception:
            pass
    # Fallback for speeds via sysfs
    sys_net = Path("/sys/class/net")
    if sys_net.exists():
        for path in sys_net.iterdir():
            if path.name == "lo":
                continue
            if any(n.name == path.name for n in nics):
                continue
            speed_path = path / "speed"
            mac_path = path / "address"
            speed = None
            mac = None
            try:
                if speed_path.exists():
                    speed = int(speed_path.read_text().strip())
                if mac_path.exists():
                    mac = mac_path.read_text().strip()
            except Exception:
                pass
            nics.append(NicInfo(name=path.name, speed_mbps=speed, mac=mac))
    return nics


def _collect_pci() -> list[PciDevice]:
    devices: list[PciDevice] = []
    if shutil.which("lspci") is None:
        return devices
    raw = _run(["lspci", "-mm"])
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        slot = parts[0].strip()
        cls = parts[1].strip().strip('"')
        vendor = parts[2].strip().strip('"')
        device = parts[3].strip().strip('"') if len(parts) > 3 else None
        devices.append(PciDevice(slot=slot, cls=cls, vendor=vendor, device=device))
    return devices


def _collect_smart(disks: Iterable[DiskInfo]) -> list[SmartStatus]:
    statuses: list[SmartStatus] = []
    if shutil.which("smartctl") is None:
        return statuses
    for disk in disks:
        dev_path = f"/dev/{disk.name}"
        info_out = _run(["smartctl", "-iH", dev_path], timeout=8.0)
        if not info_out:
            continue
        model = None
        serial = None
        health = None
        for line in info_out.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = k.strip().lower()
            val = v.strip()
            if key == "device model":
                model = val
            elif key == "serial number":
                serial = val
            elif "health" in key:
                health = val
        statuses.append(SmartStatus(device=dev_path, model=model, serial=serial, health=health))
    return statuses


def collect_system_info() -> SystemInfo:
    """Collect system information into a structured dataclass."""
    now = datetime.now(timezone.utc).isoformat()
    uname = platform.uname()
    os_release = _read_os_release()
    host = uname.node or platform.node() or ""

    platform_info = {
        "system": uname.system,
        "node": uname.node,
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
        "processor": uname.processor,
    }
    os_info = {
        "name": os_release.get("PRETTY_NAME") or os_release.get("NAME") or "",
        "id": os_release.get("ID") or "",
        "version": os_release.get("VERSION") or "",
        "version_id": os_release.get("VERSION_ID") or "",
    }
    kernel_info = {
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
        "system": uname.system,
        "processor": uname.processor,
    }
    python_info = {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable or "",
    }

    disks = _collect_disks()
    info = SystemInfo(
        host=host,
        timestamp=now,
        os=os_info,
        kernel=kernel_info,
        platform=platform_info,
        python=python_info,
        cpu=_collect_cpu(),
        memory=_collect_memory(),
        disks=disks,
        nics=_collect_nics(),
        pci=_collect_pci(),
        smart=_collect_smart(disks),
    )
    return info


def main(argv: list[str] | None = None) -> int:
    """Backwards-compatible CLI entrypoint (delegates to system_info_cli)."""
    from lb_runner.system_info_cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
