"""Tests for run context builder helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lb_app.services.run_context_builder import RunContextBuilder, apply_overrides
from lb_runner.api import BenchmarkConfig, PlatformConfig, WorkloadConfig


pytestmark = pytest.mark.unit_ui


class _FakeConfigService:
    def __init__(self, cfg: BenchmarkConfig, platform_cfg: PlatformConfig, resolved: Path):
        self._cfg = cfg
        self._platform_cfg = platform_cfg
        self._resolved = resolved
        self.last_config_path: Path | None = None

    def load_for_read(self, config_path: Path | None):
        self.last_config_path = config_path
        return self._cfg, self._resolved, None

    def load_platform_config(self):
        return self._platform_cfg, Path("platform.json"), True


class _DummyUI:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.successes: list[str] = []

    def show_warning(self, message: str) -> None:
        self.warnings.append(message)

    def show_info(self, message: str) -> None:
        self.infos.append(message)

    def show_success(self, message: str) -> None:
        self.successes.append(message)


def test_apply_overrides_sets_intensity_and_debug() -> None:
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", options={})}

    apply_overrides(cfg, intensity="high", debug=True)

    assert cfg.workloads["stress_ng"].intensity == "high"
    assert cfg.workloads["stress_ng"].options["debug"] is True


def test_context_builder_filters_disabled_workloads(tmp_path: Path) -> None:
    cfg = BenchmarkConfig()
    cfg.output_dir = tmp_path / "out"
    cfg.report_dir = tmp_path / "reports"
    cfg.data_export_dir = tmp_path / "exports"
    cfg.plugin_assets = {"fio": object()}
    cfg.workloads = {
        "stress_ng": WorkloadConfig(plugin="stress_ng"),
        "fio": WorkloadConfig(plugin="fio"),
    }

    platform_cfg = PlatformConfig(plugins={"stress_ng": False})
    config_path = Path("config.json")
    config_service = _FakeConfigService(cfg, platform_cfg, config_path)
    ui = _DummyUI()
    builder = RunContextBuilder(lambda: SimpleNamespace())

    context = builder.create_session(
        config_service,
        tests=None,
        config_path=config_path,
        repetitions=2,
        debug=True,
        intensity="high",
        ui_adapter=ui,
        setup=False,
    )

    assert context.config_path == config_path
    assert context.target_tests == ["fio"]
    assert context.config.repetitions == 2
    assert context.config.remote_execution.run_setup is False
    assert context.config.remote_execution.run_teardown is False
    assert context.config.remote_execution.enabled is True
    assert ui.warnings and "Skipping workloads disabled by platform config" in ui.warnings[0]
    assert context.config.output_dir.exists()
    assert context.config.report_dir.exists()
    assert context.config.data_export_dir.exists()
