"""Unit tests for the local K6Runner."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_plugins.plugins.peva_faas.services.k6_runner import K6Runner, K6ExecutionError
from lb_plugins.plugins.peva_faas.config import DfaasFunctionConfig


@pytest.fixture
def k6_runner() -> K6Runner:
    return K6Runner(
        gateway_url="http://gateway:8080",
        duration="10s",
        log_stream_enabled=True,
    )


def test_execute_success_writes_artifacts(
    k6_runner: K6Runner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executed_cmds: list[list[str]] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.StringIO("k6 ok\n")

        def wait(self) -> int:
            return 0

    def fake_popen(cmd, **_kwargs):
        executed_cmds.append(cmd)
        summary_path = Path(cmd[cmd.index("--summary-export") + 1])
        summary_path.write_text(json.dumps({"metrics": {"http_reqs": {"value": 1}}}))
        return FakeProcess()

    monkeypatch.setattr(
        "lb_plugins.plugins.peva_faas.services.k6_runner.subprocess.Popen", fake_popen
    )

    result = k6_runner.execute(
        config_id="cfg1",
        script="console.log('hi');",
        target_name="target1",
        run_id="run1",
        metric_ids={"fn": "fn_id"},
        output_dir=tmp_path,
    )

    assert result.summary == {"metrics": {"http_reqs": {"value": 1}}}
    assert executed_cmds

    workspace = tmp_path / "k6" / "target1" / "run1" / "cfg1"
    assert (workspace / "script.js").exists()
    assert (workspace / "k6.log").exists()
    assert (workspace / "summary.json").exists()


def test_execute_failure_on_nonzero_exit(
    k6_runner: K6Runner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.StringIO("boom\n")

        def wait(self) -> int:
            return 2

    def fake_popen(cmd, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "lb_plugins.plugins.peva_faas.services.k6_runner.subprocess.Popen", fake_popen
    )

    with pytest.raises(K6ExecutionError, match="exit code 2"):
        k6_runner.execute(
            config_id="cfg1",
            script="script",
            target_name="target1",
            run_id="run1",
            metric_ids={"fn": "fn_id"},
            output_dir=tmp_path,
        )


def test_execute_failure_missing_summary(
    k6_runner: K6Runner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.StringIO("ok\n")

        def wait(self) -> int:
            return 0

    def fake_popen(cmd, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "lb_plugins.plugins.peva_faas.services.k6_runner.subprocess.Popen", fake_popen
    )

    with pytest.raises(K6ExecutionError, match="summary file not found"):
        k6_runner.execute(
            config_id="cfg1",
            script="script",
            target_name="target1",
            run_id="run1",
            metric_ids={"fn": "fn_id"},
            output_dir=tmp_path,
        )


def test_stream_handler_emits_logs(k6_runner: K6Runner) -> None:
    callback = MagicMock()
    k6_runner._log_callback = callback
    k6_runner._log_to_logger = False

    k6_runner._stream_handler("Line 1\nLine 2  ")

    assert callback.call_count == 2
    callback.assert_any_call("k6: Line 1")
    callback.assert_any_call("k6: Line 2")


def test_build_script_handles_functions(k6_runner: K6Runner) -> None:
    script, metric_ids = k6_runner.build_script(
        [("figlet", 10)],
        [DfaasFunctionConfig(name="figlet", method="POST", body="hi")],
    )
    assert "constant-arrival-rate" in script
    assert metric_ids["figlet"] in script
