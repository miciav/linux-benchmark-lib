"""Characterization tests for RunService session creation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lb_app.services.run_service import RunService
from lb_runner.api import BenchmarkConfig, PlatformConfig, WorkloadConfig

pytestmark = pytest.mark.unit_ui


class _FakeConfigService:
    def __init__(self, cfg: BenchmarkConfig, platform_cfg: PlatformConfig, resolved: Path):
        self._cfg = cfg
        self._platform_cfg = platform_cfg
        self._resolved = resolved
        self.load_calls = 0

    def load_for_read(self, config_path: Path | None):
        self.load_calls += 1
        return self._cfg, self._resolved, None

    def load_platform_config(self):
        return self._platform_cfg, Path("platform.json"), True


def test_run_service_create_session_applies_overrides(tmp_path: Path) -> None:
    cfg = BenchmarkConfig()
    cfg.output_dir = tmp_path / "out"
    cfg.report_dir = tmp_path / "reports"
    cfg.data_export_dir = tmp_path / "exports"
    cfg.plugin_assets = {"stress_ng": object()}
    cfg.workloads = {
        "stress_ng": WorkloadConfig(plugin="stress_ng", options={}),
    }
    platform_cfg = PlatformConfig()
    config_path = Path("config.json")
    config_service = _FakeConfigService(cfg, platform_cfg, config_path)

    service = RunService(lambda: SimpleNamespace())
    context = service.create_session(
        config_service,
        config_path=config_path,
        repetitions=2,
        debug=True,
        intensity="high",
        setup=False,
    )

    assert context.config_path == config_path
    assert context.target_tests == ["stress_ng"]
    assert context.config.repetitions == 2
    assert context.config.remote_execution.run_setup is False
    assert context.config.remote_execution.run_teardown is False
    assert context.config.remote_execution.enabled is True
    assert context.config.workloads["stress_ng"].intensity == "high"
    assert context.config.workloads["stress_ng"].options["debug"] is True
    assert context.config.output_dir.exists()
    assert context.config.report_dir.exists()
    assert context.config.data_export_dir.exists()
