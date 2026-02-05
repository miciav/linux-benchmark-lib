from __future__ import annotations

import pytest

from lb_plugins.observability import (
    GrafanaAssets,
    GrafanaDashboardAsset,
    GrafanaDatasourceAsset,
)
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

    def import_dashboard(
        self, dashboard, *, overwrite: bool = True, folder_id: int = 0
    ):
        self.dashboard_calls.append({"dashboard": dashboard, "overwrite": overwrite})
        return {"id": 1}


class TokenGrafanaClient(DummyGrafanaClient):
    instances: list["TokenGrafanaClient"] = []

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        org_id: int = 1,
        basic_auth: tuple[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.org_id = org_id
        self.basic_auth = basic_auth
        TokenGrafanaClient.instances.append(self)

    def create_service_account_token(self, *, name: str, role: str = "Admin") -> str:
        return f"{name}-token"


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
        dashboards=(GrafanaDashboardAsset(name="dfaas", dashboard={"title": "DFaaS"}),),
    )

    summary = configure_grafana(
        grafana_url="http://grafana:3000",
        grafana_api_key="token",
        grafana_admin_user=None,
        grafana_admin_password=None,
        grafana_token_name=None,
        grafana_org_id=1,
        loki_endpoint="http://loki:3100/loki/api/v1/push",
        assets=assets,
        client=client,
    )

    assert isinstance(summary, GrafanaConfigSummary)
    assert summary.datasources_configured == 1
    assert summary.dashboards_configured == 2
    assert client.datasource_calls[0][0] == "loki"
    assert client.datasource_calls[0][1] == "http://loki:3100"
    assert client.datasource_calls[1][0] == "dfaas-prom"
    assert len(client.dashboard_calls) == 2


def test_configure_grafana_requires_api_key() -> None:
    with pytest.raises(ValueError):
        configure_grafana(
            grafana_url="http://grafana:3000",
            grafana_api_key=None,
            grafana_admin_user=None,
            grafana_admin_password=None,
            grafana_token_name=None,
            grafana_org_id=1,
            loki_endpoint="http://loki:3100",
            assets=GrafanaAssets(),
        )


def test_configure_grafana_creates_token_with_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TokenGrafanaClient.instances.clear()
    monkeypatch.setattr(
        "lb_provisioner.services.loki_grafana.GrafanaClient",
        TokenGrafanaClient,
    )

    assets = GrafanaAssets()

    configure_grafana(
        grafana_url="http://grafana:3000",
        grafana_api_key=None,
        grafana_admin_user="admin",
        grafana_admin_password="secret",
        grafana_token_name="lb-token",
        grafana_org_id=1,
        loki_endpoint="http://loki:3100",
        assets=assets,
    )

    assert len(TokenGrafanaClient.instances) == 2
    bootstrap = TokenGrafanaClient.instances[0]
    provisioned = TokenGrafanaClient.instances[1]
    assert bootstrap.basic_auth == ("admin", "secret")
    assert provisioned.api_key == "lb-token-token"
