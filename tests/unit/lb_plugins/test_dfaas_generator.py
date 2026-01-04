from __future__ import annotations

import json
import time
import pytest

from lb_plugins.plugins.dfaas.generator import (
    DfaasGenerator,
    dominates,
    generate_configurations,
    generate_rates_list,
)
from lb_plugins.plugins.dfaas.services.k6_runner import K6Runner
from lb_plugins.plugins.dfaas.config import DfaasConfig, DfaasFunctionConfig

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


def test_build_k6_extra_args_includes_outputs_and_tags() -> None:
    args = K6Runner._build_extra_args(
        outputs=["loki=http://localhost:3100/loki/api/v1/push"],
        tags={"run_id": "run-1", "component": "k6"},
    )

    assert "--out" in args
    assert "loki=http://localhost:3100/loki/api/v1/push" in args
    assert "--tag" in args
    assert "run_id=run-1" in args
    assert "component=k6" in args


def test_k6_outputs_adds_loki_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LB_LOKI_ENABLED", "1")
    monkeypatch.setenv("LB_LOKI_ENDPOINT", "http://controller:3100")
    cfg = DfaasConfig(k6_outputs=["json=stdout"])
    generator = DfaasGenerator(cfg)

    outputs = generator._resolve_k6_outputs()

    assert "json=stdout" in outputs
    assert any(output.startswith("loki=") for output in outputs)


def test_dfaas_generator_grafana_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generator should create Grafana annotations for run events."""
    from lb_plugins.plugins.dfaas.generator import DfaasGenerator, _RunContext, ExecutionContext
    from lb_plugins.plugins.dfaas.config import DfaasConfig, GrafanaConfig
    from unittest.mock import MagicMock

    config = DfaasConfig(
        grafana=GrafanaConfig(enabled=True, url="http://grafana", api_key="key"),
    )
    # Inject execution context with known host
    exec_ctx = ExecutionContext(host="localhost", repetition=1, total_repetitions=1)
    generator = DfaasGenerator(config, execution_context=exec_ctx)
    
    # Mock Grafana client
    mock_client = MagicMock()
    generator._grafana_client = mock_client
    generator._grafana_dashboard_id = 123

    # Create dummy context
    ctx = MagicMock(spec=_RunContext)
    ctx.run_id = "test-run"
    
    # Test run start
    generator._annotate_run_start(ctx)
    # Threading used, so we need to wait or mock threading/queue
    # The current impl uses threading.Thread(daemon=True).start()
    # We can mock threading.Thread to run synchronously
    
    with monkeypatch.context() as m:
        m.setattr("threading.Thread", lambda target, daemon: MagicMock(start=target))
        
        generator._annotate_run_start(ctx)
        mock_client.create_annotation.assert_called_with(
            text="DFaaS run start (test-run)",
            tags=['run_id:test-run', 'workload:dfaas', 'component:dfaas', 'repetition:1', 'host:localhost', 'phase:run', 'event:run_start'],
            dashboard_id=123,
            time_ms=pytest.approx(int(time.time() * 1000), abs=1000)
        )

        generator._annotate_run_end(ctx)
        assert "event:run_end" in mock_client.create_annotation.call_args[1]["tags"]

        generator._annotate_config_change(ctx, "cfg1", "a=1")
        assert "event:config" in mock_client.create_annotation.call_args[1]["tags"]

        generator._annotate_overload(ctx, "cfg1", "a=1", 1)
        assert "event:overload" in mock_client.create_annotation.call_args[1]["tags"]

        generator._annotate_error(ctx, "cfg1", "oops")
        assert "event:error" in mock_client.create_annotation.call_args[1]["tags"]


def test_k6_runner_incorporates_args_into_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """K6Runner should pass outputs and tags to the ansible command."""
    from unittest.mock import MagicMock
    
    k6_runner = K6Runner(
        k6_host="host", k6_user="user", k6_ssh_key="key", k6_port=22,
        k6_workspace_root="/root", gateway_url="http://gw", duration="30s"
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr("subprocess.run", mock_run)
    # Mock playbook existence check
    monkeypatch.setattr("pathlib.Path.exists", lambda s: True)
    monkeypatch.setattr("pathlib.Path.read_text", lambda s, encoding=None: "{}")
    monkeypatch.setattr("pathlib.Path.write_text", lambda s, t, encoding=None: None)

    k6_runner.execute(
        "cfg1", "script", "target", "run1",
        outputs=["loki=http://loki"],
        tags={"custom": "tag"}
    )

    call_args = mock_run.call_args[0][0]
    # Check that extra args are passed as JSON in -e
    # The command is [ansible-playbook, ..., -e, json_string]
    # We need to find the json string for k6_extra_args
    found = False
    for arg in call_args:
        if isinstance(arg, str) and "k6_extra_args" in arg:
            data = json.loads(arg)
            extra = data["k6_extra_args"]
            assert "--out" in extra
            assert "loki=http://loki" in extra
            assert "--tag" in extra
            assert "custom=tag" in extra
            found = True
    assert found
