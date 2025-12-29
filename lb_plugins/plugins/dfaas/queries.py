from __future__ import annotations

from dataclasses import dataclass
import json
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml


class PrometheusQueryError(RuntimeError):
    """Raised when Prometheus queries fail or return empty data."""


@dataclass(frozen=True)
class QueryDefinition:
    name: str
    query: str
    range: bool = True
    step: str = "10s"
    enabled_if: str | None = None


def load_queries(path: Path) -> list[QueryDefinition]:
    data = yaml.safe_load(path.read_text()) or {}
    items = data.get("queries", [])
    if not isinstance(items, list):
        raise ValueError("queries.yml must contain a 'queries' list.")
    definitions: list[QueryDefinition] = []
    for entry in items:
        if not isinstance(entry, dict):
            raise ValueError("Each query entry must be a mapping.")
        name = entry.get("name")
        query = entry.get("query")
        if not name or not query:
            raise ValueError("Query entries require 'name' and 'query'.")
        definitions.append(
            QueryDefinition(
                name=name,
                query=query,
                range=bool(entry.get("range", True)),
                step=str(entry.get("step", "10s")),
                enabled_if=entry.get("enabled_if"),
            )
        )
    return definitions


def filter_queries(
    queries: Iterable[QueryDefinition], *, scaphandre_enabled: bool
) -> list[QueryDefinition]:
    filtered: list[QueryDefinition] = []
    for query in queries:
        if query.enabled_if == "scaphandre" and not scaphandre_enabled:
            continue
        filtered.append(query)
    return filtered


def render_query(
    template: str,
    *,
    time_span: str,
    function_name: str | None = None,
    pid_regex: str | None = None,
) -> str:
    rendered = template.replace("{time_span}", time_span)
    if function_name is not None:
        rendered = rendered.replace("{function_name}", function_name)
    if pid_regex is not None:
        rendered = rendered.replace("{pid_regex}", pid_regex)
    return rendered


def parse_instant_value(payload: dict[str, Any]) -> float:
    result = payload.get("data", {}).get("result", [])
    if not result:
        raise PrometheusQueryError("Empty instant query result.")
    value = result[0].get("value")
    if not value or len(value) < 2:
        raise PrometheusQueryError("Malformed instant query result.")
    return float(value[1])


def parse_range_average(payload: dict[str, Any]) -> float:
    result = payload.get("data", {}).get("result", [])
    if not result:
        raise PrometheusQueryError("Empty range query result.")
    values = result[0].get("values", [])
    if not values:
        raise PrometheusQueryError("Malformed range query result.")
    total = sum(float(item[1]) for item in values)
    return total / len(values)


class PrometheusQueryRunner:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        retry_seconds: int = 30,
        sleep_seconds: int = 1,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._retry_seconds = retry_seconds
        self._sleep_seconds = sleep_seconds

    def execute(
        self,
        query: QueryDefinition,
        *,
        time_span: str,
        start_time: float | None = None,
        end_time: float | None = None,
        function_name: str | None = None,
        pid_regex: str | None = None,
    ) -> float:
        rendered = render_query(
            query.query,
            time_span=time_span,
            function_name=function_name,
            pid_regex=pid_regex,
        )
        if query.range and start_time is not None and end_time is not None:
            return self._execute_range(
                rendered, start_time=start_time, end_time=end_time, step=query.step
            )
        return self._execute_instant(rendered)

    def _execute_range(
        self, query: str, *, start_time: float, end_time: float, step: str
    ) -> float:
        url = f"{self._base_url}/api/v1/query_range"
        params = {
            "query": query,
            "start": str(start_time),
            "end": str(end_time),
            "step": step,
        }
        payload = self._retry_until_result(url, params)
        return parse_range_average(payload)

    def _execute_instant(self, query: str) -> float:
        url = f"{self._base_url}/api/v1/query"
        params = {"query": query}
        payload = self._retry_until_result(url, params)
        return parse_instant_value(payload)

    def _retry_until_result(
        self, url: str, params: dict[str, str]
    ) -> dict[str, Any]:
        start = time.time()
        while True:
            payload = self._request_json(url, params)
            if payload.get("data", {}).get("result"):
                return payload
            if time.time() - start > self._retry_seconds:
                raise PrometheusQueryError("Prometheus query timed out.")
            time.sleep(self._sleep_seconds)

    def _request_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        query_string = urlencode(params)
        request = Request(f"{url}?{query_string}")
        with urlopen(request, timeout=self._timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
