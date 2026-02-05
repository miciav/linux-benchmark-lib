from __future__ import annotations

import pytest

from lb_plugins.plugins.dfaas.config import DfaasConfig
from lb_plugins.plugins.dfaas.context import ExecutionContext
from lb_plugins.plugins.dfaas.generator import DfaasGenerator
from lb_plugins.plugins.dfaas.grafana_assets import GRAFANA_DASHBOARD_UID
from lb_plugins.plugins.dfaas.services.annotation_service import DfaasAnnotationService
import lb_plugins.plugins.dfaas.services.annotation_service as annotation_mod

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
    exec_ctx = ExecutionContext(
        host="remote-host",
        host_address="10.0.0.5",
        repetition=1,
        total_repetitions=1,
    )
    generator = DfaasGenerator(cfg, execution_context=exec_ctx)

    resolved = generator._resolve_prometheus_url("10.0.0.5")

    assert resolved == "http://10.0.0.5:30411"


def test_resolve_prometheus_url_replaces_host_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = DfaasConfig(prometheus_url="http://{host.address}:30411")
    generator = DfaasGenerator(cfg)

    # Mock _get_local_ip to return a stable IP (used when target_name is empty)
    monkeypatch.setattr(generator, "_get_local_ip", lambda: "192.168.1.50")

    # Pass empty target_name to trigger _get_local_ip() fallback
    resolved = generator._resolve_prometheus_url("")

    assert resolved == "http://192.168.1.50:30411"


def test_init_grafana_resolves_dashboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(annotation_mod, "GrafanaClient", FakeGrafanaClient)

    cfg = DfaasConfig(
        grafana={
            "enabled": True,
            "url": "http://grafana.local:3000",
            "api_key": "token",
            "org_id": 1,
        },
        prometheus_url="http://127.0.0.1:30411",
    )
    exec_ctx = ExecutionContext(host="host", repetition=1, total_repetitions=1)
    annotations = DfaasAnnotationService(cfg.grafana, exec_ctx)

    annotations.setup()

    assert isinstance(annotations._client, FakeGrafanaClient)
    assert annotations.dashboard_uid == GRAFANA_DASHBOARD_UID
    assert annotations._dashboard_id == 7
    assert annotations._client.requested_uid == GRAFANA_DASHBOARD_UID


def test_init_grafana_skips_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(annotation_mod, "GrafanaClient", UnhealthyGrafanaClient)

    cfg = DfaasConfig(
        grafana={"enabled": True, "url": "http://grafana.local:3000"},
        prometheus_url="http://127.0.0.1:30411",
    )
    exec_ctx = ExecutionContext(host="host", repetition=1, total_repetitions=1)
    annotations = DfaasAnnotationService(cfg.grafana, exec_ctx)

    annotations.setup()

    assert annotations._client is None
