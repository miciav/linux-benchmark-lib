import base64
import io
import json
from unittest.mock import MagicMock
from urllib import error
from urllib.request import Request

import pytest

from lb_common.observability import grafana_client as grafana_mod
from lb_common.observability.grafana_client import GrafanaClient

pytestmark = [pytest.mark.unit_runner]


class DummyResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_base_url_requires_http_scheme() -> None:
    with pytest.raises(ValueError):
        GrafanaClient(base_url="file:///tmp/grafana")


def test_request_sends_headers_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _get_header(req: Request, name: str) -> str | None:
        header = req.get_header(name)
        if header is not None:
            return header
        for key, value in req.headers.items():
            if key.lower() == name.lower():
                return value
        return None

    def fake_urlopen(req: Request, timeout: float | None = None) -> DummyResponse:
        captured["auth"] = _get_header(req, "Authorization")
        captured["org"] = _get_header(req, "X-Grafana-Org-Id")
        captured["content_type"] = _get_header(req, "Content-Type")
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        captured["data"] = req.data
        return DummyResponse(200, '{"ok": true}')

    monkeypatch.setattr(grafana_mod.request, "urlopen", fake_urlopen)

    client = GrafanaClient(base_url="http://grafana", api_key="token", org_id=2)
    status, data = client._request(
        "POST",
        "/api/test",
        payload={"a": 1},
        expected_statuses={200},
    )

    assert status == 200
    assert data == {"ok": True}
    assert captured["auth"] == "Bearer token"
    assert captured["org"] == "2"
    assert captured["content_type"] == "application/json"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://grafana/api/test"
    payload_bytes = captured["data"]
    assert isinstance(payload_bytes, (bytes, bytearray))
    assert json.loads(payload_bytes.decode("utf-8")) == {"a": 1}


def test_request_sends_basic_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _get_header(req: Request, name: str) -> str | None:
        header = req.get_header(name)
        if header is not None:
            return header
        for key, value in req.headers.items():
            if key.lower() == name.lower():
                return value
        return None

    def fake_urlopen(req: Request, timeout: float | None = None) -> DummyResponse:
        captured["auth"] = _get_header(req, "Authorization")
        return DummyResponse(200, '{"ok": true}')

    monkeypatch.setattr(grafana_mod.request, "urlopen", fake_urlopen)

    client = GrafanaClient(
        base_url="http://grafana",
        basic_auth=("admin", "secret"),
    )
    client._request("GET", "/api/test", expected_statuses={200})

    expected = base64.b64encode(b"admin:secret").decode("ascii")
    assert captured["auth"] == f"Basic {expected}"


def test_request_handles_expected_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(req: Request, timeout: float | None = None) -> DummyResponse:
        raise error.HTTPError(
            req.full_url,
            404,
            "Not Found",
            hdrs=None,
            fp=io.BytesIO(b'{"message": "missing"}'),
        )

    monkeypatch.setattr(grafana_mod.request, "urlopen", fake_urlopen)

    client = GrafanaClient(base_url="http://grafana")
    status, data = client._request(
        "GET",
        "/api/missing",
        expected_statuses={404},
    )

    assert status == 404
    assert data == {"message": "missing"}


def test_create_service_account_token_reuses_existing_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    responses = [
        (
            "POST",
            "/api/serviceaccounts",
            (
                400,
                {"messageId": "serviceaccounts.ErrAlreadyExists", "message": "exists"},
            ),
        ),
        (
            "GET",
            "/api/serviceaccounts/search?query=lb-observability",
            (200, {"serviceAccounts": [{"id": 5, "name": "lb-observability"}]}),
        ),
        (
            "POST",
            "/api/serviceaccounts/5/tokens",
            (200, {"key": "token-123"}),
        ),
    ]

    def fake_request(
        method: str,
        path: str,
        payload: dict | None = None,
        expected_statuses: set[int] | None = None,
    ) -> tuple[int, dict | None]:
        calls.append((method, path, payload))
        expected_method, expected_path, response = responses.pop(0)
        assert method == expected_method
        assert path == expected_path
        return response

    client = GrafanaClient(
        base_url="http://grafana",
        basic_auth=("admin", "secret"),
    )
    monkeypatch.setattr(client, "_request", fake_request)

    token = client.create_service_account_token(name="lb-observability")

    assert token == "token-123"
    assert calls[0][2] == {"name": "lb-observability", "role": "Admin"}


def test_upsert_datasource_updates_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GrafanaClient(base_url="http://grafana")
    request_mock = MagicMock(side_effect=[(200, {"id": 9}), (200, {"ok": True})])
    monkeypatch.setattr(client, "_request", request_mock)

    result = client.upsert_datasource(name="prom", url="http://prom:9090")

    assert result == 9
    assert request_mock.call_count == 2
    assert request_mock.call_args_list[0].args[1] == "/api/datasources/name/prom"
    _, kwargs = request_mock.call_args_list[1]
    payload = kwargs["payload"]
    assert payload["id"] == 9
    assert payload["name"] == "prom"
    assert payload["url"] == "http://prom:9090"


def test_upsert_datasource_creates_with_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GrafanaClient(base_url="http://grafana")
    request_mock = MagicMock(
        side_effect=[(404, None), (201, {"datasource": {"id": 7}})]
    )
    monkeypatch.setattr(client, "_request", request_mock)

    result = client.upsert_datasource(
        name="prom",
        url="http://prom:9090",
        basic_auth=("user", "pass"),
        json_data={"httpMethod": "POST"},
    )

    assert result == 7
    assert request_mock.call_args_list[0].args[1] == "/api/datasources/name/prom"
    _, kwargs = request_mock.call_args_list[1]
    payload = kwargs["payload"]
    assert payload["basicAuth"] is True
    assert payload["basicAuthUser"] == "user"
    assert payload["secureJsonData"]["basicAuthPassword"] == "pass"
    assert payload["jsonData"]["httpMethod"] == "POST"
