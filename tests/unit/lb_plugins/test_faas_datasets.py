import pytest

from lb_plugins.plugins._faas_shared.config_enumerator import config_id
from lb_plugins.plugins._faas_shared.datasets import long_rows

pytestmark = pytest.mark.unit_plugins


def test_long_rows_split_functions_and_node_metrics() -> None:
    row = {
        "function_env": "env",
        "rate_function_env": 5,
        "success_rate_function_env": "1.000",
        "cpu_usage_function_env": "0.409",
        "ram_usage_function_env": "6875136.0",
        "power_usage_function_env": "nan",
        "replica_env": 1,
        "overloaded_function_env": 0,
        "medium_latency_function_env": "3.426",
        "function_figlet": "",
        "rate_function_figlet": "",
        "cpu_usage_node": "13.4",
        "rest_seconds": 0,
    }
    results = [
        {
            "repetition": 1,
            "generator_result": {
                "dfaas_functions": ["env", "figlet"],
                "dfaas_results": [row],
            },
        }
    ]
    rows = long_rows(results, "dfaas")
    env = {r["metric"]: r for r in rows if r["function"] == "env"}
    assert env["cpu_usage"]["value"] == "0.409"
    assert env["cpu_usage"]["unit"] == "%"
    assert env["medium_latency"]["unit"] == "ms"
    assert env["cpu_usage"]["config_id"] == config_id([("env", 5)])
    assert env["cpu_usage"]["rate"] == 5
    assert not [r for r in rows if r["function"] == "figlet"]
    node = {r["metric"]: r for r in rows if r["function"] == ""}
    assert node["cpu_usage_node"]["unit"] == "%"
    assert node["rest_seconds"]["rate"] == ""
    assert {r["repetition"] for r in rows} == {1}


def test_long_rows_tolerate_a_missing_rate() -> None:
    results = [
        {
            "repetition": 2,
            "generator_result": {
                "peva_faas_functions": ["figlet"],
                "peva_faas_results": [{"function_figlet": "figlet", "rest_seconds": 5}],
            },
        }
    ]
    rows = long_rows(results, "peva_faas")
    figlet = [r for r in rows if r["function"] == "figlet"]
    assert figlet and {r["rate"] for r in figlet} == {""}
    assert {r["metric"] for r in rows if r["function"] == ""} == {"rest_seconds"}
