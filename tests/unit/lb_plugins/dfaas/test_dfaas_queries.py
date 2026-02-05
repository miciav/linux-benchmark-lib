from pathlib import Path

import pytest

from lb_plugins.plugins.dfaas.queries import (
    load_queries,
    parse_instant_value,
    parse_range_average,
    render_query,
)

pytestmark = [pytest.mark.unit_plugins]


def test_queries_load_from_file() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    queries = load_queries(
        repo_root / "lb_plugins" / "plugins" / "dfaas" / "queries.yml"
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
