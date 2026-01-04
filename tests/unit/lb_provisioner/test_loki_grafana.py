from __future__ import annotations

import pytest

from lb_plugins.observability import GrafanaAssets, GrafanaDashboardAsset, GrafanaDatasourceAsset
from lb_provisioner.services.loki_grafana import (
    GrafanaConfigSummary,
    configure_grafana,
    normalize_loki_base_url,
)

pytestmark = [pytest.mark.unit_provisioner]


class DummyGrafanaClient:
    def __init__(self) -> None:
        self.datasource_calls: list[tuple[str, str, str]] = []
        self.dashboard_calls: list[dict[str, object]] = []

    def health_check(self):
        return True, {"version": "test"}

    def upsert_datasource(
        self,
        *,
        name: str,
        url: str,
        datasource_type: str = "prometheus",
        access: str = "proxy",
        is_default: bool = False,
        basic_auth=None,
        json_data=None,
    ):
        self.datasource_calls.append((name, url, datasource_type))
        return 1

    def import_dashboard(self, dashboard, *, overwrite: bool = True, folder_id: int = 0):
        self.dashboard_calls.append({"dashboard": dashboard, "overwrite": overwrite})
        return {"id": 1}


def test_normalize_loki_base_url() -> None:
    assert (
        normalize_loki_base_url("http://localhost:3100/loki/api/v1/push")
        == "http://localhost:3100"
    )
    assert normalize_loki_base_url("http://localhost:3100") == "http://localhost:3100"


def test_configure_grafana_uses_assets() -> None:
    client = DummyGrafanaClient()
    assets = GrafanaAssets(
        datasources=(
            GrafanaDatasourceAsset(
                name="dfaas-prom",
                url="http://prom:9090",
                datasource_type="prometheus",
            ),
        ),
        dashboards=(
            GrafanaDashboardAsset(name="dfaas", dashboard={"title": "DFaaS"}),
        ),
    )

    summary = configure_grafana(
        grafana_url="http://grafana:3000",
        grafana_api_key="token",
        grafana_org_id=1,
        loki_endpoint="http://loki:3100/loki/api/v1/push",
        assets=assets,
        client=client,
    )

    assert isinstance(summary, GrafanaConfigSummary)
    assert summary.datasources_configured == 1
    assert summary.dashboards_configured == 1
    assert client.datasource_calls[0][0] == "loki"
    assert client.datasource_calls[0][1] == "http://loki:3100"
    assert client.datasource_calls[1][0] == "dfaas-prom"


def test_configure_grafana_requires_api_key() -> None:
    with pytest.raises(ValueError):
        configure_grafana(
            grafana_url="http://grafana:3000",
            grafana_api_key=None,
            grafana_org_id=1,
            loki_endpoint="http://loki:3100",
            assets=GrafanaAssets(),
        )
