"""Tests for ConfigRepository IO boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from lb_app.services.config_repository import ConfigRepository
from lb_app.services.config_service import ConfigService
from lb_runner.api import BenchmarkConfig, PlatformConfig, WorkloadConfig


pytestmark = pytest.mark.unit_ui


def test_repository_roundtrip_config(tmp_path: Path) -> None:
    repo = ConfigRepository(config_home=tmp_path)
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    path = tmp_path / "config.json"

    repo.write_benchmark_config(cfg, path)
    loaded = repo.read_benchmark_config(path)

    assert "stress_ng" in loaded.workloads
    assert loaded.workloads["stress_ng"].plugin == "stress_ng"


def test_repository_reads_stale_pointer(tmp_path: Path) -> None:
    repo = ConfigRepository(config_home=tmp_path)
    repo.ensure_home()
    missing_path = tmp_path / "missing.json"
    repo.pointer.write_text(str(missing_path))

    resolved, stale = repo.read_saved_config_path()

    assert resolved is None
    assert stale == missing_path


def test_load_for_read_applies_platform_defaults(tmp_path: Path) -> None:
    platform_output = tmp_path / "output"
    repo = ConfigRepository(config_home=tmp_path)
    repo.write_platform_config(PlatformConfig(output_dir=platform_output))
    service = ConfigService(config_home=tmp_path)

    cfg, resolved, stale = service.load_for_read(None)

    assert resolved is None
    assert stale is None
    assert cfg.output_dir == platform_output
