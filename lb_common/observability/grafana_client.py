"""Grafana API client for DFaaS integrations."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib import request, error, parse


def _validate_http_url(url: str, label: str) -> str:
    parsed = parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be an http(s) URL, got: {url}")
    return url


@dataclass
class GrafanaClient:
    """Lightweight Grafana API client with retry support."""

    base_url: str
    api_key: str | None = None
    basic_auth: tuple[str, str] | None = None
    org_id: int = 1
    timeout_seconds: float = 5.0
    max_retries: int = 3
    backoff_base: float = 0.5
    backoff_factor: float = 2.0

    def __post_init__(self) -> None:
        self.base_url = _validate_http_url(
            self.base_url.rstrip("/"), "Grafana base_url"
        )

    def health_check(self) -> tuple[bool, dict[str, Any] | None]:
        try:
            status, data = self._request("GET", "/api/health", expected_statuses={200})
            return status == 200, data
        except Exception:
            return False, None

    def upsert_datasource(
        self,
        *,
        name: str,
        url: str,
        datasource_type: str = "prometheus",
        access: str = "proxy",
        is_default: bool = False,
        basic_auth: tuple[str, str] | None = None,
        json_data: Mapping[str, Any] | None = None,
    ) -> int | None:
        safe_name = parse.quote(name, safe="")
        status, data = self._request(
            "GET",
            f"/api/datasources/name/{safe_name}",
            expected_statuses={200, 404},
        )
        payload = {
            "name": name,
            "type": datasource_type,
            "url": url,
            "access": access,
            "isDefault": is_default,
        }
        if json_data:
            payload["jsonData"] = dict(json_data)
        if basic_auth:
            payload["basicAuth"] = True
            payload["basicAuthUser"] = basic_auth[0]
            payload["secureJsonData"] = {"basicAuthPassword": basic_auth[1]}

        if status == 200 and isinstance(data, dict):
            datasource_id = data.get("id")
            if datasource_id is not None:
                payload["id"] = datasource_id
                self._request(
                    "PUT",
                    f"/api/datasources/{datasource_id}",
                    payload=payload,
                    expected_statuses={200},
                )
                return int(datasource_id)
        status, data = self._request(
            "POST",
            "/api/datasources",
            payload=payload,
            expected_statuses={200, 201},
        )
        if isinstance(data, dict):
            return data.get("datasource", {}).get("id")
        return None

    def import_dashboard(
        self,
        dashboard: Mapping[str, Any],
        *,
        overwrite: bool = True,
        folder_id: int = 0,
    ) -> dict[str, Any] | None:
        payload = {
            "dashboard": dict(dashboard),
            "overwrite": overwrite,
            "folderId": folder_id,
        }
        _, data = self._request(
            "POST",
            "/api/dashboards/db",
            payload=payload,
            expected_statuses={200},
        )
        return data if isinstance(data, dict) else None

    def get_dashboard_by_uid(self, uid: str) -> dict[str, Any] | None:
        """Fetch a dashboard by its UID."""
        status, data = self._request(
            "GET",
            f"/api/dashboards/uid/{uid}",
            expected_statuses={200, 404},
        )
        if status == 200 and isinstance(data, dict):
            return data
        return None

    def create_annotation(
        self,
        *,
        text: str,
        tags: list[str] | None = None,
        dashboard_id: int | None = None,
        panel_id: int | None = None,
        time_ms: int | None = None,
        time_end_ms: int | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "text": text,
            "tags": tags or [],
        }
        if dashboard_id is not None:
            payload["dashboardId"] = dashboard_id
        if panel_id is not None:
            payload["panelId"] = panel_id
        if time_ms is not None:
            payload["time"] = time_ms
        if time_end_ms is not None:
            payload["timeEnd"] = time_end_ms
        _, data = self._request(
            "POST",
            "/api/annotations",
            payload=payload,
            expected_statuses={200},
        )
        return data if isinstance(data, dict) else None

    def create_service_account_token(
        self,
        *,
        name: str,
        role: str = "Admin",
    ) -> str:
        """Create a Grafana service account and return its token."""
        if not self.basic_auth:
            raise ValueError("Basic auth credentials are required to create a token.")
        status, data = self._request(
            "POST",
            "/api/serviceaccounts",
            payload={"name": name, "role": role},
            expected_statuses={200, 201, 400},
        )
        service_id: int | None = None
        if status in {200, 201} and isinstance(data, dict):
            service_id = data.get("id")
        elif status == 400 and self._is_already_exists_error(data):
            service_id = self._lookup_service_account_id(name)
        if not service_id:
            raise RuntimeError("Grafana service account creation failed.")
        token = self._create_service_account_token(int(service_id), name)
        if not token:
            raise RuntimeError("Grafana service account token creation failed.")
        return token

    def create_api_key(
        self,
        *,
        name: str,
        role: str = "Admin",
        seconds_to_live: int | None = None,
    ) -> str:
        """Create a Grafana API key and return the token."""
        if not self.basic_auth:
            raise ValueError("Basic auth credentials are required to create an API key.")
        payload: dict[str, Any] = {"name": name, "role": role}
        if seconds_to_live:
            payload["secondsToLive"] = seconds_to_live
        status, data = self._request(
            "POST",
            "/api/auth/keys",
            payload=payload,
            expected_statuses={200, 201, 400},
        )
        if status == 400 and self._is_already_exists_error(data):
            suffix = int(time.time())
            payload["name"] = f"{name}-{suffix}"
            status, data = self._request(
                "POST",
                "/api/auth/keys",
                payload=payload,
                expected_statuses={200, 201},
            )
        token = data.get("key") if isinstance(data, dict) else None
        if not token:
            raise RuntimeError("Grafana API key creation failed.")
        return token

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        expected_statuses: set[int] | None = None,
    ) -> tuple[int, dict[str, Any] | None]:
        expected = expected_statuses or {200}
        url = f"{self.base_url.rstrip('/')}{path}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.basic_auth:
            user, password = self.basic_auth
            token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode(
                "ascii"
            )
            headers["Authorization"] = f"Basic {token}"
        if self.org_id:
            headers["X-Grafana-Org-Id"] = str(self.org_id)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        for attempt in range(self.max_retries + 1):
            try:
                req = request.Request(url, data=data, headers=headers, method=method)
                with request.urlopen(  # nosec B310
                    req, timeout=self.timeout_seconds
                ) as resp:
                    status = resp.status
                    body = resp.read().decode("utf-8") if resp is not None else ""
                parsed = self._parse_json(body)
                if status in expected:
                    return status, parsed
                if 500 <= status and attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"Grafana API error {status}: {body}")
            except error.HTTPError as exc:
                status = exc.code
                body = exc.read().decode("utf-8") if exc.fp else ""
                parsed = self._parse_json(body)
                if status in expected:
                    return status, parsed
                if status >= 500 and attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"Grafana API error {status}: {body}") from exc
            except error.URLError as exc:
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"Grafana API request failed: {exc}") from exc
        raise RuntimeError("Grafana API request failed after retries.")

    def _lookup_service_account_id(self, name: str) -> int | None:
        query = parse.quote(name, safe="")
        _, data = self._request(
            "GET",
            f"/api/serviceaccounts/search?query={query}",
            expected_statuses={200},
        )
        if not isinstance(data, dict):
            return None
        accounts = data.get("serviceAccounts") or data.get("serviceaccounts") or []
        for account in accounts:
            if isinstance(account, dict) and account.get("name") == name:
                account_id = account.get("id")
                if account_id is not None:
                    return int(account_id)
        return None

    def _create_service_account_token(self, service_id: int, name: str) -> str | None:
        status, data = self._request(
            "POST",
            f"/api/serviceaccounts/{service_id}/tokens",
            payload={"name": name},
            expected_statuses={200, 201, 400},
        )
        if status in {200, 201}:
            return data.get("key") if isinstance(data, dict) else None
        if status == 400 and self._is_already_exists_error(data):
            suffix = int(time.time())
            return self._create_service_account_token(service_id, f"{name}-{suffix}")
        return None

    @staticmethod
    def _is_already_exists_error(data: dict[str, Any] | None) -> bool:
        if not isinstance(data, dict):
            return False
        message = str(data.get("message") or "").lower()
        message_id = str(data.get("messageId") or "")
        if "already exists" in message:
            return True
        if "AlreadyExists" in message_id:
            return True
        return False

    @staticmethod
    def _parse_json(body: str) -> dict[str, Any] | None:
        if not body:
            return None
        try:
            parsed = json.loads(body)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self.backoff_base * (self.backoff_factor ** attempt)
        if delay > 0:
            time.sleep(delay)
