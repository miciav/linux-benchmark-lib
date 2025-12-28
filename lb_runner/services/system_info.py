"""System information collection utilities.

Collects host static data (OS, kernel, CPU, memory, disks, network) and optional
hardware details (PCI, SMART). Designed to run both locally and on remote hosts
provisioned by Ansible.
"""

from __future__ import annotations

import argparse
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lb_runner.services import system_info_collectors as collectors
from lb_runner.services.system_info_io import write_outputs
from lb_runner.services.system_info_types import (
    DiskInfo,
    KernelModule,
    NicInfo,
    PciDevice,
    SmartStatus,
    SystemInfo,
    SystemService,
)


_run = collectors._run
_json_output = collectors._json_output
_read_os_release = collectors._read_os_release
psutil = collectors.psutil
shutil = collectors.shutil
_collect_cpu = collectors._collect_cpu
_collect_memory = collectors._collect_memory
_collect_disks = collectors._collect_disks
_collect_nics = collectors._collect_nics
_collect_pci = collectors._collect_pci
_collect_smart = collectors._collect_smart
_collect_kernel_modules = collectors._collect_kernel_modules
_collect_services = collectors._collect_services
_calculate_fingerprint = collectors._calculate_fingerprint


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
    modules = _collect_kernel_modules()
    services = _collect_services()

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
        modules=modules,
        services=services,
    )

    info.fingerprint = _calculate_fingerprint(info)
    return info


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for system information collection."""
    parser = argparse.ArgumentParser(description="Collect system information into JSON/CSV.")
    parser.add_argument("--json", type=Path, help="Path to write JSON output")
    parser.add_argument("--csv", type=Path, help="Path to write CSV output (flattened)")
    args = parser.parse_args(argv)

    info = collect_system_info()
    write_outputs(info, args.json, args.csv)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
