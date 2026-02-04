from __future__ import annotations

import pytest

from lb_plugins.plugins.peva_faas.config import DfaasConfig, DfaasFunctionConfig
from lb_plugins.plugins.peva_faas.generator import DfaasGenerator

pytestmark = [pytest.mark.unit_plugins]


def _make_config(**overrides: object) -> DfaasConfig:
    defaults = {
        "k3s_host": "10.0.0.5",
        "prometheus_url": "http://{host.address}:30411",
        "gateway_url": "http://{host.address}:31112",
        "functions": [DfaasFunctionConfig(name="dummy")],
    }
    defaults.update(overrides)
    return DfaasConfig(**defaults)


def test_resolve_prometheus_url_uses_k3s_host_template() -> None:
    config = _make_config(k3s_host="10.0.0.99")
    gen = DfaasGenerator(config)
    assert gen._resolve_prometheus_url() == "http://10.0.0.99:30411"


def test_resolve_prometheus_url_replaces_localhost() -> None:
    config = _make_config(k3s_host="192.168.1.50", prometheus_url="http://localhost:30411")
    gen = DfaasGenerator(config)
    assert gen._resolve_prometheus_url() == "http://192.168.1.50:30411"


def test_resolve_prometheus_url_leaves_static_host() -> None:
    config = _make_config(prometheus_url="http://static-host:9090")
    gen = DfaasGenerator(config)
    assert gen._resolve_prometheus_url() == "http://static-host:9090"


def test_gateway_url_resolves_with_k3s_host() -> None:
    config = _make_config(k3s_host="192.168.1.88")
    generator = DfaasGenerator(config)
    assert generator._k6_runner.gateway_url == "http://192.168.1.88:31112"
