from pathlib import Path

import pytest
from pydantic import ValidationError

from lb_plugins.plugins.peva_faas.config import (
    DfaasConfig,
    _looks_like_default_queries_path,
)

pytestmark = [pytest.mark.unit_plugins]


def test_config_path_load_with_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "peva_faas_config.yml"
    config_path.write_text(
        "\n".join(
            [
                "common:",
                "  timeout_buffer: 5",
                "plugins:",
                "  peva_faas:",
                '    k3s_host: "10.0.0.50"',
                "    functions:",
                '      - name: "figlet"',
                '        method: "POST"',
                '        body: "Hello PEVA-faas!"',
                "        headers:",
                '          Content-Type: "text/plain"',
                "    rate_strategy:",
                '      type: "linear"',
                "      min_rate: 0",
                "      max_rate: 20",
                "      step: 10",
                "    combinations:",
                "      min_functions: 1",
                "      max_functions: 2",
            ]
        )
    )

    config = DfaasConfig(
        config_path=config_path, rate_strategy={"type": "linear", "max_rate": 50}
    )

    assert config.timeout_buffer == 5
    assert config.k3s_host == "10.0.0.50"
    assert config.rate_strategy.min_rate == 0
    assert config.rate_strategy.max_rate == 50


def test_invalid_rate_bounds_rejected() -> None:
    with pytest.raises(ValidationError):
        DfaasConfig(
            rate_strategy={"type": "linear", "min_rate": 20, "max_rate": 10, "step": 10}
        )


def test_invalid_duration_rejected() -> None:
    with pytest.raises(ValidationError):
        DfaasConfig(duration="30")


def test_grafana_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LB_GRAFANA_ENABLED", "1")
    monkeypatch.setenv("LB_GRAFANA_URL", "http://grafana.local:3000")
    monkeypatch.setenv("LB_GRAFANA_API_KEY", "token")
    monkeypatch.setenv("LB_GRAFANA_ORG_ID", "2")

    config = DfaasConfig()

    assert config.grafana.enabled is True
    assert config.grafana.url == "http://grafana.local:3000"
    assert config.grafana.api_key == "token"
    assert config.grafana.org_id == 2


def test_default_queries_path_is_absolute() -> None:
    config = DfaasConfig()
    path = Path(config.queries_path)
    assert path.is_absolute()
    assert path.name == "queries.yml"
    assert path.exists()


def test_legacy_dfaas_queries_path_not_considered_default() -> None:
    assert (
        _looks_like_default_queries_path(Path("lb_plugins/plugins/dfaas/queries.yml"))
        is False
    )


def test_config_path_ignores_legacy_dfaas_plugin_section(tmp_path: Path) -> None:
    config_path = tmp_path / "peva_faas_config.yml"
    config_path.write_text(
        "\n".join(
            [
                "plugins:",
                "  dfaas:",
                '    k3s_host: "10.0.0.50"',
            ]
        )
    )

    config = DfaasConfig(config_path=config_path)

    assert config.k3s_host == "127.0.0.1"


def test_memory_defaults_use_duckdb_and_core_preload_only() -> None:
    config = DfaasConfig()

    assert config.memory.backend == "duckdb"
    assert config.memory.preload_raw_debug is False


def test_micro_batch_requires_positive_batch_size() -> None:
    with pytest.raises(ValidationError):
        DfaasConfig(selection_mode="micro_batch", micro_batch_size=0)


def test_custom_algorithm_entrypoint_is_optional() -> None:
    config = DfaasConfig()

    assert config.algorithm_entrypoint is None
