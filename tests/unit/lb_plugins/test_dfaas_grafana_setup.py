from __future__ import annotations

import pytest

from lb_plugins.plugins.dfaas.config import DfaasConfig
from lb_plugins.plugins.dfaas.generator import DfaasGenerator
from lb_plugins.plugins.dfaas.grafana_assets import GRAFANA_DASHBOARD_UID
import lb_plugins.plugins.dfaas.generator as generator_mod

pytestmark = [pytest.mark.unit_plugins]


class FakeGrafanaClient:
    def __init__(self, base_url: str, api_key: str | None, org_id: int) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.org_id = org_id
        self.requested_uid: str | None = None

    def health_check(self) -> tuple[bool, dict[str, object] | None]:
        return True, {"status": "ok"}

    def get_dashboard_by_uid(self, uid: str) -> dict[str, object] | None:
        self.requested_uid = uid
        return {"dashboard": {"id": 7, "uid": uid}}


class UnhealthyGrafanaClient(FakeGrafanaClient):
    def health_check(self) -> tuple[bool, dict[str, object] | None]:
        return False, None


def test_resolve_prometheus_url_rewrites_localhost() -> None:
    cfg = DfaasConfig(prometheus_url="http://127.0.0.1:30411")
    generator = DfaasGenerator(cfg)

    resolved = generator._resolve_prometheus_url("10.0.0.5")

    assert resolved == "http://10.0.0.5:30411"


def test_init_grafana_resolves_dashboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generator_mod, "GrafanaClient", FakeGrafanaClient)

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

    generator._init_grafana()

    assert isinstance(generator._grafana_client, FakeGrafanaClient)
    assert generator._grafana_dashboard_uid == GRAFANA_DASHBOARD_UID
    assert generator._grafana_dashboard_id == 7
    assert generator._grafana_client.requested_uid == GRAFANA_DASHBOARD_UID


def test_init_grafana_skips_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generator_mod, "GrafanaClient", UnhealthyGrafanaClient)

    cfg = DfaasConfig(
        grafana={"enabled": True, "url": "http://grafana.local:3000"},
        prometheus_url="http://127.0.0.1:30411",
    )
    generator = DfaasGenerator(cfg)

    generator._init_grafana()

    assert generator._grafana_client is None
