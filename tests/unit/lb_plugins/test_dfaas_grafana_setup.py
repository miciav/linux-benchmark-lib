from __future__ import annotations

import pytest

from lb_plugins.plugins.dfaas.config import DfaasConfig
from lb_plugins.plugins.dfaas.generator import (
    DfaasGenerator,
    _GRAFANA_DATASOURCE_NAME,
)
import lb_plugins.plugins.dfaas.generator as generator_mod

pytestmark = [pytest.mark.unit_plugins]


class FakeGrafanaClient:
    def __init__(self, base_url: str, api_key: str | None, org_id: int) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.org_id = org_id
        self.upsert_args: dict[str, object] | None = None
        self.imported_dashboard: dict[str, object] | None = None

    def health_check(self) -> tuple[bool, dict[str, object] | None]:
        return True, {"status": "ok"}

    def upsert_datasource(self, **kwargs: object) -> int | None:
        self.upsert_args = kwargs
        return 42

    def import_dashboard(
        self, dashboard: object, **kwargs: object
    ) -> dict[str, object] | None:
        self.imported_dashboard = dashboard
        return {"id": 7, "uid": "dfaas"}


class UnhealthyGrafanaClient(FakeGrafanaClient):
    def health_check(self) -> tuple[bool, dict[str, object] | None]:
        return False, None


def test_resolve_prometheus_url_rewrites_localhost() -> None:
    cfg = DfaasConfig(prometheus_url="http://127.0.0.1:30411")
    generator = DfaasGenerator(cfg)

    resolved = generator._resolve_prometheus_url("10.0.0.5")

    assert resolved == "http://10.0.0.5:30411"


def test_configure_grafana_sets_datasource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generator_mod, "GrafanaClient", FakeGrafanaClient)

    def _fake_dashboard(self) -> dict[str, object]:
        return {"title": "DFaaS Overview"}

    monkeypatch.setattr(DfaasGenerator, "_load_grafana_dashboard", _fake_dashboard)

    cfg = DfaasConfig(
        grafana={
            "enabled": True,
            "url": "http://grafana.local:3000",
            "api_key": "token",
            "org_id": 1,
        },
        prometheus_url="http://127.0.0.1:30411",
    )
    generator = DfaasGenerator(cfg)

    generator._configure_grafana("10.0.0.5")

    assert isinstance(generator._grafana_client, FakeGrafanaClient)
    assert generator._grafana_dashboard_id == 7
    assert generator._grafana_dashboard_uid == "dfaas"
    assert generator._grafana_client.upsert_args is not None
    assert generator._grafana_client.upsert_args["name"] == _GRAFANA_DATASOURCE_NAME
    assert (
        generator._grafana_client.upsert_args["url"]
        == "http://10.0.0.5:30411"
    )


def test_configure_grafana_skips_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generator_mod, "GrafanaClient", UnhealthyGrafanaClient)

    cfg = DfaasConfig(
        grafana={"enabled": True, "url": "http://grafana.local:3000"},
        prometheus_url="http://127.0.0.1:30411",
    )
    generator = DfaasGenerator(cfg)

    generator._configure_grafana("10.0.0.5")

    assert generator._grafana_client is None
