from __future__ import annotations

import json
from dataclasses import dataclass
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


def test_dashboard_loads_from_file(tmp_path: Path) -> None:
    payload = {"title": "DFaaS"}
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps(payload))

    asset = GrafanaDashboardAsset(name="dfaas", path=path)
    loaded = asset.load()

    assert loaded == payload

