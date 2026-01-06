import pytest

from lb_app.api import ConfigService, RunService
from lb_runner.api import BenchmarkConfig, PlatformConfig, WorkloadConfig

pytestmark = pytest.mark.unit_ui


def test_platform_config_persists_plugin_enablement(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    service = ConfigService()

    cfg, path = service.set_plugin_enabled("dfaas", True)

    assert path == tmp_path / "lb" / "platform.json"
    assert cfg.is_plugin_enabled("dfaas") is True

    loaded, loaded_path, exists = service.load_platform_config()
    assert exists is True
    assert loaded_path == path
    assert loaded.is_plugin_enabled("dfaas") is True
    assert loaded.is_plugin_enabled("fio") is True


def test_resolve_target_tests_filters_disabled():
    cfg = BenchmarkConfig()
    cfg.workloads = {
        "stress_ng": WorkloadConfig(plugin="stress_ng"),
        "fio": WorkloadConfig(plugin="fio"),
    }
    platform_cfg = PlatformConfig(plugins={"stress_ng": False})

    allowed = RunService._resolve_target_tests(cfg, None, platform_cfg, None)

    assert allowed == ["fio"]

    with pytest.raises(ValueError):
        RunService._resolve_target_tests(
            cfg,
            ["stress_ng"],
            platform_cfg,
            None,
        )
