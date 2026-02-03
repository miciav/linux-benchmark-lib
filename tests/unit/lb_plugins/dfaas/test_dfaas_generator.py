from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from lb_plugins.plugins.peva_faas.generator import DfaasGenerator
from lb_plugins.plugins.peva_faas.context import ExecutionContext
from lb_plugins.plugins.peva_faas.services.k6_runner import K6Runner
from lb_plugins.plugins.peva_faas.services.annotation_service import DfaasAnnotationService
from lb_plugins.plugins.peva_faas.services.plan_builder import (
    DfaasPlanBuilder,
    dominates,
    generate_configurations,
    generate_rates_list,
)
from lb_plugins.plugins.peva_faas.config import (
    DfaasCombinationConfig,
    DfaasConfig,
    DfaasFunctionConfig,
    LinearRateStrategy,
)

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


def test_plan_builder_generates_deterministic_configs() -> None:
    config = DfaasConfig(
        functions=[
            DfaasFunctionConfig(name="b", method="GET", body=""),
            DfaasFunctionConfig(name="a", method="GET", body=""),
        ],
        rate_strategy=LinearRateStrategy(min_rate=0, max_rate=10, step=10),
        combinations=DfaasCombinationConfig(min_functions=1, max_functions=2),
    )
    builder = DfaasPlanBuilder(config)
    function_names = builder.build_function_names()
    rates = builder.build_rates()
    configs = builder.build_configurations(
        function_names,
        rates,
        rates_by_function=builder.build_rates_by_function(rates),
    )

    assert function_names == ["a", "b"]
    assert rates == [0, 10]
    assert configs == [
        [("a", 0)],
        [("a", 10)],
        [("b", 0)],
        [("b", 10)],
    ]


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


def test_parse_k6_summary_missing_metrics_raises() -> None:
    k6_runner = K6Runner(
        k6_host="127.0.0.1",
        k6_user="ubuntu",
        k6_ssh_key="~/.ssh/id_rsa",
        k6_port=22,
        k6_workspace_root="/home/ubuntu/.dfaas-k6",
        gateway_url="http://example.com:31112",
        duration="30s",
    )
    summary = {"metrics": {}}
    with pytest.raises(ValueError, match="Missing k6 summary metrics"):
        k6_runner.parse_summary(summary, {"figlet": "fn_figlet"})


def test_build_k6_command_includes_outputs_and_tags() -> None:
    """Test that _build_k6_command properly formats outputs and tags."""
    k6_runner = K6Runner(
        k6_host="host", k6_user="user", k6_ssh_key="key", k6_port=22,
        k6_workspace_root="/root", gateway_url="http://gw", duration="30s"
    )
    cmd = k6_runner._build_k6_command(
        script_path="/path/script.js",
        summary_path="/path/summary.json",
        outputs=["loki=http://localhost:3100/loki/api/v1/push"],
        tags={"run_id": "run-1", "component": "k6"},
    )

    assert "--out" in cmd
    assert "loki=http://localhost:3100/loki/api/v1/push" in cmd
    assert "--tag" in cmd
    assert "run_id=run-1" in cmd
    assert "component=k6" in cmd
    assert "--summary-export" in cmd


def test_k6_outputs_returns_configured_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Standard k6 doesn't support Loki - only return explicitly configured outputs."""
    monkeypatch.setenv("LB_LOKI_ENABLED", "1")  # Should be ignored
    cfg = DfaasConfig(k6_outputs=["json=stdout", "csv=results.csv"])
    generator = DfaasGenerator(cfg)

    outputs = generator._resolve_k6_outputs()

    assert outputs == ["json=stdout", "csv=results.csv"]
    # Loki should NOT be auto-added (standard k6 doesn't support it)
    assert not any(output.startswith("loki=") for output in outputs)


def test_dfaas_annotations_emit_grafana_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Annotation service should create Grafana annotations for run events."""
    from lb_plugins.plugins.peva_faas.config import DfaasConfig, GrafanaConfig
    from unittest.mock import MagicMock

    config = DfaasConfig(
        grafana=GrafanaConfig(enabled=True, url="http://grafana", api_key="key"),
    )
    exec_ctx = ExecutionContext(host="localhost", repetition=1, total_repetitions=1)
    annotations = DfaasAnnotationService(config.grafana, exec_ctx)
    mock_client = MagicMock()
    annotations._client = mock_client
    annotations._dashboard_id = 123

    with monkeypatch.context() as m:
        m.setattr("threading.Thread", lambda target, daemon: MagicMock(start=target))

        annotations.annotate_run_start("test-run")
        mock_client.create_annotation.assert_called_with(
            text="DFaaS run start (test-run)",
            tags=[
                "run_id:test-run",
                "workload:dfaas",
                "component:dfaas",
                "repetition:1",
                "host:localhost",
                "phase:run",
                "event:run_start",
            ],
            dashboard_id=123,
            time_ms=pytest.approx(int(time.time() * 1000), abs=1000),
        )

        annotations.annotate_run_end("test-run")
        assert "event:run_end" in mock_client.create_annotation.call_args[1]["tags"]

        annotations.annotate_config_change("test-run", "cfg1", "a=1")
        assert "event:config" in mock_client.create_annotation.call_args[1]["tags"]

        annotations.annotate_overload("test-run", "cfg1", "a=1", 1)
        assert "event:overload" in mock_client.create_annotation.call_args[1]["tags"]

        annotations.annotate_error("test-run", "cfg1", "oops")
        assert "event:error" in mock_client.create_annotation.call_args[1]["tags"]


def test_k6_log_event_skips_when_lb_event_handler_present() -> None:
    from lb_runner.services.log_handler import LBEventLogHandler
    from lb_plugins.plugins.peva_faas.services.log_manager import DfaasLogManager

    cfg = DfaasConfig()
    exec_ctx = ExecutionContext(
        host="localhost",
        repetition=1,
        total_repetitions=1,
        event_logging_enabled=True,
    )
    log_manager = DfaasLogManager(
        config=cfg,
        exec_ctx=exec_ctx,
        logger=logging.getLogger("dfaas-test"),
        event_emitter=Mock(),
    )
    log_manager.set_run_id("run-1")

    root_logger = logging.getLogger()
    handler = LBEventLogHandler(
        run_id="run-1",
        host="localhost",
        workload="dfaas",
        repetition=1,
        total_repetitions=1,
    )
    root_logger.addHandler(handler)
    try:
        log_manager.emit_k6_log("hello")
        log_manager.event_emitter.emit.assert_not_called()
    finally:
        root_logger.removeHandler(handler)


def test_k6_runner_execute_passes_outputs_and_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """K6Runner.execute() should include outputs and tags in the k6 command."""
    from unittest.mock import MagicMock, patch

    k6_runner = K6Runner(
        k6_host="host", k6_user="user", k6_ssh_key="key", k6_port=22,
        k6_workspace_root="/root", gateway_url="http://gw", duration="30s"
    )

    # Mock Fabric Connection
    mock_conn = MagicMock()
    mock_conn.run.return_value = MagicMock(failed=False)
    mock_conn.get = MagicMock()

    # Track the k6 command that gets executed
    executed_commands = []

    def capture_run(cmd, **kwargs):
        executed_commands.append(cmd)
        return MagicMock(failed=False)

    mock_conn.run.side_effect = capture_run

    with patch.object(k6_runner, "_get_connection", return_value=mock_conn):
        with patch("tempfile.NamedTemporaryFile") as mock_temp:
            mock_temp.return_value.__enter__.return_value.name = "/tmp/test"
            with patch("os.unlink"):
                with patch("pathlib.Path.read_text", return_value='{"metrics": {}}'):
                    k6_runner.execute(
                        "cfg1", "script", "target", "run1",
                        metric_ids={"fn": "fn_id"},
                        outputs=["loki=http://loki"],
                        tags={"custom": "tag"},
                    )

    # Find the k6 run command (not mkdir)
    k6_cmd = next((c for c in executed_commands if "k6 run" in c), None)
    assert k6_cmd is not None, f"No k6 run command found in: {executed_commands}"
    assert "--out" in k6_cmd
    assert "loki=http://loki" in k6_cmd
    assert "--tag" in k6_cmd
    assert "custom=tag" in k6_cmd


def test_get_function_replicas_parses_replicas_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = (
        "NAME IMAGE INVOCATIONS REPLICAS\n"
        "figlet ghcr.io/openfaas/figlet:latest 10 3\n"
        "eat-memory ghcr.io/openfaas/eat-memory:latest 5 1\n"
    )
    monkeypatch.setattr(
        "lb_plugins.plugins.peva_faas.generator.subprocess.run",
        lambda *args, **kwargs: Mock(stdout=output),
    )
    cfg = DfaasConfig(
        functions=[
            DfaasFunctionConfig(name="figlet"),
            DfaasFunctionConfig(name="eat-memory"),
        ]
    )
    generator = DfaasGenerator(cfg)
    replicas = generator._get_function_replicas(["figlet", "eat-memory"])

    assert replicas["figlet"] == 3
    assert replicas["eat-memory"] == 1


def test_validate_environment_requires_faas_cli_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_path = tmp_path / "id_rsa"
    key_path.write_text("dummy")
    cfg = DfaasConfig(k6_ssh_key=str(key_path))
    generator = DfaasGenerator(cfg)

    def fake_run(cmd, **_kwargs):
        if cmd[:2] == ["which", "faas-cli"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr(
        "lb_plugins.plugins.peva_faas.generator.subprocess.run", fake_run
    )

    assert generator._validate_environment() is True
