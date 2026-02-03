import csv
import platform
import subprocess
import tempfile
from pathlib import Path

import pytest

from lb_plugins.api import CommandGenerator, DDConfig, DDGenerator, DDPlugin

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]


def test_dd_defaults() -> None:
    cfg = DDConfig()
    plugin = DDPlugin()
    assert plugin.name == "dd"
    assert plugin.description
    gen = plugin.create_generator(cfg)
    assert isinstance(gen, DDGenerator)
    assert isinstance(gen, CommandGenerator)


def test_dd_build_command_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    cfg = DDConfig(count=5, conv="fdatasync", oflag="direct")
    cmd = DDGenerator(cfg)._build_command()
    assert "if=/dev/zero" in cmd
    assert f"of={cfg.of_path}" in cmd
    output_path = Path(cfg.of_path)
    assert output_path.is_relative_to(Path(tempfile.gettempdir()))
    assert "count=5" in cmd
    assert "conv=fdatasync" in cmd
    assert "oflag=direct" in cmd
    assert "status=progress" in cmd


def test_dd_build_command_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    cfg = DDConfig(count=1, conv="fdatasync", oflag="direct")
    cmd = DDGenerator(cfg)._build_command()
    assert "count=1" in cmd
    assert "conv=sync" in cmd
    assert not any(part.startswith("oflag=") for part in cmd)


def test_dd_popen_kwargs() -> None:
    cfg = DDConfig()
    gen = DDGenerator(cfg)
    kwargs = gen._popen_kwargs()
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.PIPE
    assert kwargs["text"] is True


def test_dd_export_summarizes_stderr(tmp_path: Path) -> None:
    plugin = DDPlugin()
    stderr = (
        "1602224128 bytes (1.6 GB, 1.5 GiB) copied, 1 s, 1.5 GB/s\n"
        "8589934592 bytes (8.6 GB, 8.0 GiB) copied, 5.85511 s, 1.5 GB/s\n"
        "2048+0 records in\n"
        "2048+0 records out\n"
        "8589934592 bytes (8.6 GB, 8.0 GiB) copied, 5.85511 s, 1.5 GB/s\n"
    )
    results = [
        {
            "repetition": 1,
            "duration_seconds": 6.1,
            "success": True,
            "generator_result": {
                "stdout": "",
                "stderr": stderr,
                "returncode": 0,
                "command": "dd if=/dev/zero of=/tmp/foo bs=4M count=2048",
                "max_retries": 0,
                "tags": [],
            },
        }
    ]
    paths = plugin.export_results_to_csv(
        results=results, output_dir=tmp_path, run_id="run-1", test_name="dd"
    )
    assert paths
    csv_path = paths[0]
    assert csv_path.exists()

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)

    assert row["generator_stderr"] == (
        "8589934592 bytes (8.6 GB, 8.0 GiB) copied, 5.85511 s, 1.5 GB/s"
    )
    assert int(float(row["dd_bytes"])) == 8589934592
    assert row["dd_rate_unit"] == "GB/s"
    assert float(row["dd_seconds"]) == pytest.approx(5.85511)
    assert float(row["dd_bytes_per_sec"]) == pytest.approx(1467083383.9, rel=1e-6)
