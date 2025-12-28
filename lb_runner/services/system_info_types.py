"""Dataclasses describing system information snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


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
class KernelModule:
    name: str
    size: int


@dataclass
class SystemService:
    name: str
    state: str


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
    modules: list[KernelModule] = field(default_factory=list)
    services: list[SystemService] = field(default_factory=list)
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "timestamp": self.timestamp,
            "fingerprint": self.fingerprint,
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
            "modules": [asdict(m) for m in self.modules],
            "services": [asdict(s) for s in self.services],
        }

    def to_csv_rows(self) -> list[dict[str, str]]:
        """Flatten into key/value rows suitable for CSV."""
        rows: list[dict[str, str]] = []

        def add(category: str, name: str, value: Any) -> None:
            rows.append({"category": category, "name": name, "value": str(value)})

        add("meta", "timestamp", self.timestamp)
        add("meta", "fingerprint", self.fingerprint)
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
            add(
                "disk",
                disk.name,
                json.dumps({k: v for k, v in asdict(disk).items() if v is not None}),
            )
        for nic in self.nics:
            add(
                "nic",
                nic.name,
                json.dumps({k: v for k, v in asdict(nic).items() if v is not None}),
            )
        for dev in self.pci:
            add(
                "pci",
                dev.slot,
                json.dumps({k: v for k, v in asdict(dev).items() if v is not None}),
            )
        for sm in self.smart:
            add(
                "smart",
                sm.device,
                json.dumps({k: v for k, v in asdict(sm).items() if v is not None}),
            )
        for mod in self.modules:
            add("module", mod.name, str(mod.size))
        for svc in self.services:
            add("service", svc.name, svc.state)
        return rows
