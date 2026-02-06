from __future__ import annotations

from pathlib import Path

import pytest

import lb_plugins.plugins.peva_faas.queries as queries_mod
from lb_plugins.plugins.peva_faas.queries import (
    PrometheusQueryError,
    PrometheusQueryRunner,
    QueryDefinition,
    filter_queries,
    load_queries,
    parse_instant_value,
    parse_range_average,
    render_query,
)

pytestmark = [pytest.mark.unit_plugins]


def test_queries_load_from_file() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    queries = load_queries(
        repo_root / "lb_plugins" / "plugins" / "peva_faas" / "queries.yml"
    )
    names = {query.name for query in queries}
    assert "cpu_usage_node" in names
    assert "ram_usage_function" in names


def test_render_query_replaces_placeholders() -> None:
    template = "rate(http_requests_total[{time_span}]){function_name}:{pid_regex}"
    rendered = render_query(
        template, time_span="30s", function_name="figlet", pid_regex="1|2|3"
    )
    assert rendered == "rate(http_requests_total[30s])figlet:1|2|3"


def test_parse_instant_value() -> None:
    payload = {"data": {"result": [{"value": [123, "4.5"]}]}}
    assert parse_instant_value(payload) == 4.5


def test_parse_range_average() -> None:
    payload = {"data": {"result": [{"values": [[1, "2"], [2, "4"]]}]}}
    assert parse_range_average(payload) == 3.0


def test_load_queries_requires_queries_to_be_list(tmp_path: Path) -> None:
    path = tmp_path / "queries.yml"
    path.write_text("queries: {}\n")

    with pytest.raises(ValueError, match="queries.yml must contain a 'queries' list"):
        load_queries(path)


def test_load_queries_requires_valid_query_entries(tmp_path: Path) -> None:
    path = tmp_path / "queries.yml"
    path.write_text("queries:\n  - name: only-name\n")

    with pytest.raises(ValueError, match="require 'name' and 'query'"):
        load_queries(path)


def test_filter_queries_applies_scaphandre_flag() -> None:
    queries = [
        QueryDefinition(name="cpu", query="up"),
        QueryDefinition(name="power", query="power", enabled_if="scaphandre"),
    ]

    filtered = filter_queries(queries, scaphandre_enabled=False)

    assert [q.name for q in filtered] == ["cpu"]
    assert [q.name for q in filter_queries(queries, scaphandre_enabled=True)] == [
        "cpu",
        "power",
    ]


@pytest.mark.parametrize(
    "payload,error",
    [
        ({}, "Empty instant query result"),
        ({"data": {"result": [{"value": [1]}]}}, "Malformed instant query result"),
    ],
)
def test_parse_instant_value_error_paths(
    payload: dict[str, object], error: str
) -> None:
    with pytest.raises(PrometheusQueryError, match=error):
        parse_instant_value(payload)


@pytest.mark.parametrize(
    "payload,error",
    [
        ({}, "Empty range query result"),
        ({"data": {"result": [{"values": []}]}}, "Malformed range query result"),
    ],
)
def test_parse_range_average_error_paths(
    payload: dict[str, object], error: str
) -> None:
    with pytest.raises(PrometheusQueryError, match=error):
        parse_range_average(payload)


def test_runner_execute_calls_range_when_window_is_provided() -> None:
    runner = PrometheusQueryRunner("http://prom")
    query = QueryDefinition(name="cpu", query="rate(up[{time_span}])", range=True, step="5s")

    runner._execute_range = lambda *args, **kwargs: 4.2  # type: ignore[method-assign]
    runner._execute_instant = lambda *_args, **_kwargs: 0.0  # type: ignore[method-assign]

    value = runner.execute(
        query,
        time_span="30s",
        start_time=10.0,
        end_time=40.0,
    )

    assert value == 4.2


def test_runner_execute_calls_instant_for_non_range_query() -> None:
    runner = PrometheusQueryRunner("http://prom")
    query = QueryDefinition(name="cpu", query="up", range=False)

    runner._execute_instant = lambda *_args, **_kwargs: 9.1  # type: ignore[method-assign]

    value = runner.execute(query, time_span="10s")

    assert value == 9.1


def test_retry_until_result_logs_once_before_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    runner = PrometheusQueryRunner("http://prom", retry_seconds=10, sleep_seconds=0)
    payloads = [
        {"data": {"result": []}},
        {"data": {"result": []}},
        {"data": {"result": [{"value": [1, "2.0"]}]}}
    ]

    def fake_request(_url: str, _params: dict[str, str]) -> dict[str, object]:
        return payloads.pop(0)

    monkeypatch.setattr(runner, "_request_json", fake_request)
    monkeypatch.setattr(queries_mod.time, "sleep", lambda _seconds: None)
    caplog.set_level("INFO")

    payload = runner._retry_until_result("http://prom", {"query": "up"})

    assert payload["data"]["result"]
    retry_logs = [
        record.message
        for record in caplog.records
        if "Prometheus query returned no data yet" in record.message
    ]
    assert len(retry_logs) == 1


def test_retry_until_result_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = PrometheusQueryRunner("http://prom", retry_seconds=2, sleep_seconds=0)
    monkeypatch.setattr(
        runner,
        "_request_json",
        lambda _url, _params: {"data": {"result": []}},
    )
    monkeypatch.setattr(queries_mod.time, "sleep", lambda _seconds: None)

    tick = {"value": 0}

    def fake_time() -> float:
        tick["value"] += 1
        return float(tick["value"])

    monkeypatch.setattr(queries_mod.time, "time", fake_time)

    with pytest.raises(PrometheusQueryError, match="timed out"):
        runner._retry_until_result("http://prom", {"query": "up"})


def test_request_json_rejects_unsupported_url_scheme() -> None:
    runner = PrometheusQueryRunner("http://prom")

    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        runner._request_json("file:///tmp/prom", {"query": "up"})


def test_request_json_builds_request_and_parses_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = PrometheusQueryRunner("http://prom", timeout_seconds=2.5)
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def read() -> bytes:
            return b'{"data": {"result": [{"value": [1, "7.0"]}]}}'

    def fake_urlopen(request, timeout: float):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(queries_mod, "urlopen", fake_urlopen)

    payload = runner._request_json("http://prom/api/v1/query", {"query": "up"})

    assert payload["data"]["result"][0]["value"][1] == "7.0"
    assert captured["timeout"] == 2.5
    assert "query=up" in str(captured["url"])
