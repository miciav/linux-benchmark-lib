from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from pathlib import Path

import pytest

from lb_plugins.observability import (
    GrafanaAssets,
    GrafanaDashboardAsset,
    GrafanaDatasourceAsset,
    resolve_grafana_assets,
)

pytestmark = [pytest.mark.unit_plugins]


@dataclass
class DummyConfig:
    prometheus_url: str


def test_datasource_resolves_direct_url() -> None:
    asset = GrafanaDatasourceAsset(name="prom", url="http://prom:9090")
    assert asset.resolve_url(None) == "http://prom:9090"


def test_datasource_resolves_from_config_attr() -> None:
    asset = GrafanaDatasourceAsset(name="prom", url_from_config="prometheus_url")
    cfg = DummyConfig(prometheus_url="http://prom:9090")
    assert asset.resolve_url(cfg) == "http://prom:9090"


def test_datasource_resolves_from_mapping() -> None:
    asset = GrafanaDatasourceAsset(name="prom", url_from_config="prometheus_url")
    cfg = {"prometheus_url": "http://prom:9090"}
    assert asset.resolve_url(cfg) == "http://prom:9090"


def test_resolve_assets_filters_missing_urls() -> None:
    assets = GrafanaAssets(
        datasources=(
            GrafanaDatasourceAsset(name="prom", url_from_config="prometheus_url"),
            GrafanaDatasourceAsset(name="loki", url=None),
        ),
        dashboards=(),
    )
    resolved = resolve_grafana_assets(assets, {"prometheus_url": "http://prom:9090"})
    assert len(resolved.datasources) == 1
    assert resolved.datasources[0].name == "prom"
    assert resolved.datasources[0].url == "http://prom:9090"


def test_per_host_expands_datasources() -> None:
    assets = GrafanaAssets(
        datasources=(
            GrafanaDatasourceAsset(
                name="dfaas-prometheus",
                url_from_config="prometheus_url",
                per_host=True,
                name_template="DFaaS Prometheus {host.name}",
            ),
        ),
        dashboards=(),
    )
    cfg = {"prometheus_url": "http://{host.address}:30411"}
    hosts = [
        SimpleNamespace(name="node-a", address="10.0.0.10"),
        SimpleNamespace(name="node-b", address="10.0.0.11"),
    ]

    resolved = resolve_grafana_assets(assets, cfg, hosts=hosts)

    assert len(resolved.datasources) == 2
    assert resolved.datasources[0].name == "DFaaS Prometheus node-a"
    assert resolved.datasources[0].url == "http://10.0.0.10:30411"
    assert resolved.datasources[1].name == "DFaaS Prometheus node-b"


def test_per_host_requires_template_for_multiple_hosts() -> None:
    assets = GrafanaAssets(
        datasources=(
            GrafanaDatasourceAsset(
                name="dfaas-prometheus",
                url_from_config="prometheus_url",
                per_host=True,
                name_template="DFaaS Prometheus {host.name}",
            ),
        ),
        dashboards=(),
    )
    cfg = {"prometheus_url": "http://localhost:30411"}
    hosts = [
        SimpleNamespace(name="node-a", address="10.0.0.10"),
        SimpleNamespace(name="node-b", address="10.0.0.11"),
    ]

    resolved = resolve_grafana_assets(assets, cfg, hosts=hosts)

    assert resolved.datasources == ()


def test_dashboard_loads_from_file(tmp_path: Path) -> None:
    payload = {"title": "DFaaS"}
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps(payload))

    asset = GrafanaDashboardAsset(name="dfaas", path=path)
    loaded = asset.load()

    assert loaded == payload
