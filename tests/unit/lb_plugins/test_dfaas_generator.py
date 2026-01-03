from __future__ import annotations

import pytest

from lb_plugins.plugins.dfaas.generator import (
    dominates,
    generate_configurations,
    generate_rates_list,
)
from lb_plugins.plugins.dfaas.services.k6_runner import K6Runner
from lb_plugins.plugins.dfaas.config import DfaasFunctionConfig

pytestmark = [pytest.mark.unit_plugins]


def test_generate_configurations_counts() -> None:
    rates = generate_rates_list(0, 10, 10)
    configs = generate_configurations(["a", "b"], rates, 1, 3)
    assert len(configs) == 8


def test_generate_configurations_respects_per_function_rates() -> None:
    rates = generate_rates_list(0, 20, 10)
    rates_by_function = {"a": [0, 10]}
    configs = generate_configurations(
        ["a", "b"],
        rates,
        1,
        3,
        rates_by_function=rates_by_function,
    )
    assert len(configs) == 11
    assert any(config == [("b", 20)] for config in configs)
    for config in configs:
        for name, rate in config:
            if name == "a":
                assert rate in rates_by_function["a"]


def test_dominates_checks_per_function() -> None:
    base = [("a", 10), ("b", 0)]
    candidate = [("a", 10), ("b", 10)]
    assert dominates(base, candidate)
    assert not dominates(base, [("a", 0), ("b", 10)])


def test_build_k6_script_includes_scenarios() -> None:
    functions = [
        DfaasFunctionConfig(name="figlet", method="POST", body="hi"),
        DfaasFunctionConfig(name="eat-memory", method="GET", body=""),
    ]
    k6_runner = K6Runner(
        k6_host="127.0.0.1",
        k6_user="ubuntu",
        k6_ssh_key="~/.ssh/id_rsa",
        k6_port=22,
        k6_workspace_root="/home/ubuntu/.dfaas-k6",
        gateway_url="http://example.com:31112",
        duration="30s",
    )
    script, metric_ids = k6_runner.build_script(
        [("figlet", 10), ("eat-memory", 0)], functions
    )
    assert "constant-arrival-rate" in script
    assert "figlet" in script
    assert metric_ids["figlet"] in script
    assert "eat-memory" in script


def test_build_k6_script_includes_shared_dfaas_metrics() -> None:
    """Script should include shared dfaas_* metrics for efficient Prometheus queries."""
    functions = [
        DfaasFunctionConfig(name="func1", method="POST", body="test"),
    ]
    k6_runner = K6Runner(
        k6_host="127.0.0.1",
        k6_user="ubuntu",
        k6_ssh_key="~/.ssh/id_rsa",
        k6_port=22,
        k6_workspace_root="/home/ubuntu/.dfaas-k6",
        gateway_url="http://example.com:31112",
        duration="30s",
    )
    script, _ = k6_runner.build_script([("func1", 10)], functions)

    # Should have shared metrics declarations
    assert 'const dfaas_success_rate = new Rate("dfaas_success_rate")' in script
    assert 'const dfaas_latency = new Trend("dfaas_latency")' in script
    assert 'const dfaas_request_count = new Counter("dfaas_request_count")' in script

    # Should update shared metrics in exec function
    assert "dfaas_success_rate.add(ok)" in script
    assert "dfaas_latency.add(res.timings.duration)" in script
    assert "dfaas_request_count.add(1)" in script


def test_build_k6_script_includes_per_function_metrics() -> None:
    """Script should also include per-function metrics for local summary parsing."""
    functions = [
        DfaasFunctionConfig(name="func1", method="POST", body="test"),
    ]
    k6_runner = K6Runner(
        k6_host="127.0.0.1",
        k6_user="ubuntu",
        k6_ssh_key="~/.ssh/id_rsa",
        k6_port=22,
        k6_workspace_root="/home/ubuntu/.dfaas-k6",
        gateway_url="http://example.com:31112",
        duration="30s",
    )
    script, metric_ids = k6_runner.build_script([("func1", 10)], functions)
    metric_id = metric_ids["func1"]

    # Should have per-function metrics for summary parsing
    assert f'const success_rate_{metric_id} = new Rate("success_rate_{metric_id}")' in script
    assert f'const latency_{metric_id} = new Trend("latency_{metric_id}")' in script
    assert f'const request_count_{metric_id} = new Counter("request_count_{metric_id}")' in script

    # Should update per-function metrics too
    assert f"success_rate_{metric_id}.add(ok)" in script
    assert f"latency_{metric_id}.add(res.timings.duration)" in script
    assert f"request_count_{metric_id}.add(1)" in script


def test_parse_k6_summary_extracts_metrics() -> None:
    k6_runner = K6Runner(
        k6_host="127.0.0.1",
        k6_user="ubuntu",
        k6_ssh_key="~/.ssh/id_rsa",
        k6_port=22,
        k6_workspace_root="/home/ubuntu/.dfaas-k6",
        gateway_url="http://example.com:31112",
        duration="30s",
    )
    summary = {
        "metrics": {
            "success_rate_fn_figlet": {"values": {"rate": 0.9}},
            "latency_fn_figlet": {"values": {"avg": 12.5}},
            "request_count_fn_figlet": {"values": {"count": 5}},
        }
    }
    parsed = k6_runner.parse_summary(summary, {"figlet": "fn_figlet"})
    assert parsed["figlet"]["success_rate"] == 0.9
    assert parsed["figlet"]["avg_latency"] == 12.5
    assert parsed["figlet"]["request_count"] == 5
