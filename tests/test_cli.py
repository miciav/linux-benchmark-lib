import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from linux_benchmark_lib.benchmark_config import BenchmarkConfig


def _load_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import the CLI module with an isolated config home and cwd."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LB_ENABLE_TEST_CLI", "1")
    monkeypatch.chdir(tmp_path)
    if "linux_benchmark_lib.cli" in sys.modules:
        del sys.modules["linux_benchmark_lib.cli"]
    cli = importlib.import_module("linux_benchmark_lib.cli")
    importlib.reload(cli)
    return cli


def test_plugins_enable_disable_persists_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()
    config_path = tmp_path / "cfg.json"

    result = runner.invoke(
        cli.app, ["plugin", "list", "--enable", "stress_ng", "-c", str(config_path)]
    )
    assert result.exit_code == 0, result.output

    cfg = BenchmarkConfig.load(config_path)
    assert "stress_ng" in cfg.workloads
    assert cfg.workloads["stress_ng"].enabled is True

    result = runner.invoke(
        cli.app, ["plugin", "list", "--disable", "stress_ng", "-c", str(config_path)]
    )
    assert result.exit_code == 0, result.output

    cfg = BenchmarkConfig.load(config_path)
    assert cfg.workloads["stress_ng"].enabled is False


def test_plugins_shows_enabled_column(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["plugin", "list"])
    assert result.exit_code == 0, result.output
    # UI adapter prints the table directly to stdout; capture from pytest
    captured = capsys.readouterr().out
    output = result.output + captured
    assert "Enabled" in output
    assert "stress_ng" in output


def test_doctor_controller_uses_checks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    monkeypatch.setattr(cli.doctor_service, "check_controller", lambda: 0)

    result = runner.invoke(cli.app, ["doctor", "controller"])
    assert result.exit_code == 0, result.output


def test_doctor_local_tools_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()
    monkeypatch.setattr(cli.doctor_service, "check_local_tools", lambda: 1)
    result = runner.invoke(cli.app, ["doctor", "local-tools"])
    assert result.exit_code != 0


def test_plugins_conflicting_flags_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["plugin", "list", "--enable", "a", "--disable", "b"])
    assert result.exit_code != 0


def test_plugin_interactive_selection_persists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    monkeypatch.setattr(
        cli,
        "_select_plugins_interactively",
        lambda registry, enabled: {"stress_ng", "dd"},
    )

    result = runner.invoke(cli.app, ["plugin", "list", "--select"])
    assert result.exit_code == 0, result.output

    cfg_path = tmp_path / "xdg" / "lb" / "config.json"
    cfg = BenchmarkConfig.load(cfg_path)
    assert cfg.workloads["stress_ng"].enabled is True
    assert cfg.workloads["dd"].enabled is True
    assert cfg.workloads["fio"].enabled is False


def test_plugin_select_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    monkeypatch.setattr(
        cli,
        "_select_plugins_interactively",
        lambda registry, enabled: {"fio"},
    )

    result = runner.invoke(cli.app, ["plugin", "select"])
    assert result.exit_code == 0, result.output

    cfg_path = tmp_path / "xdg" / "lb" / "config.json"
    cfg = BenchmarkConfig.load(cfg_path)
    assert cfg.workloads["fio"].enabled is True
    assert cfg.workloads["stress_ng"].enabled is False


def test_plugin_root_defaults_to_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["plugin"])
    assert result.exit_code == 0, result.output
    assert "Available Workload Plugins" in result.output


def test_config_init_sets_repetitions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()
    cfg_path = tmp_path / "cfg.json"

    result = runner.invoke(
        cli.app,
        [
            "config",
            "init",
            "--path",
            str(cfg_path),
            "--no-set-default",
            "--repetitions",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    cfg = BenchmarkConfig.load(cfg_path)
    assert cfg.repetitions == 5


def test_run_command_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    cfg = BenchmarkConfig()
    # Ensure at least one workload is enabled so run does not exit early
    if "stress_ng" in cfg.workloads:
        cfg.workloads["stress_ng"].enabled = True
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)

    called = {}

    def fake_execute(context, run_id, output_callback=None, ui_adapter=None):
        called["context"] = context
        called["run_id"] = run_id
        return None

    monkeypatch.setattr(cli.run_service, "execute", fake_execute)

    result = runner.invoke(
        cli.app,
        [
            "run",
            "-c",
            str(cfg_path),
            "--run-id",
            "test-run",
            "--docker-no-build",
            "--repetitions",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert called["run_id"] == "test-run"
    assert called["context"].config.repetitions == 2


def test_run_command_allows_repetition_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    cfg = BenchmarkConfig()
    if "stress_ng" in cfg.workloads:
        cfg.workloads["stress_ng"].enabled = True
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)

    called = {}

    def fake_execute(context, run_id, output_callback=None, ui_adapter=None):
        called["context"] = context
        called["run_id"] = run_id
        return None

    monkeypatch.setattr(cli.run_service, "execute", fake_execute)

    result = runner.invoke(
        cli.app,
        [
            "run",
            "-c",
            str(cfg_path),
            "--repetitions",
            "5",
            "--run-id",
            "test-run",
            "--docker-no-build",
        ],
    )

    assert result.exit_code == 0, result.output
    assert called["run_id"] == "test-run"
    assert called["context"].config.repetitions == 5


def test_config_set_default_and_workloads_listing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    cfg = BenchmarkConfig()
    cfg_path = tmp_path / "myconfig.json"
    cfg.save(cfg_path)

    result = runner.invoke(cli.app, ["config", "set-default", str(cfg_path)])
    assert result.exit_code == 0, result.output

    # workloads listing should pick default config and show known workload
    result = runner.invoke(cli.app, ["config", "workloads"])
    assert result.exit_code == 0, result.output
    assert "stress_ng" in result.output
    # Default config keeps workloads disabled until explicitly toggled
    assert "no" in result.output


def test_config_set_repetitions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    config_path = tmp_path / "cfg.json"
    result = runner.invoke(
        cli.app, ["config", "set-repetitions", "4", "-c", str(config_path)]
    )

    assert result.exit_code == 0, result.output
    cfg = BenchmarkConfig.load(config_path)
    assert cfg.repetitions == 4


def test_multipass_helper_sets_artifacts_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    monkeypatch.setattr(cli, "_check_command", lambda name: True)
    monkeypatch.setattr(cli, "_check_import", lambda name: True)

    called = {}

    def fake_run(cmd, check, env):
        called["cmd"] = cmd
        called["env"] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    artifacts = tmp_path / "artifacts"
    result = runner.invoke(cli.app, ["test", "multipass", "-o", str(artifacts)])
    assert result.exit_code == 0, result.output

    assert called["env"]["LB_TEST_RESULTS_DIR"] == str(artifacts)
    assert called["env"]["LB_MULTIPASS_VM_COUNT"] == "1"
    cmd = called.get("cmd")
    assert cmd is not None
    assert cmd[0] == sys.executable
    assert "pytest" in cmd
    assert "tests/integration/test_multipass_benchmark.py" in cmd


def test_multipass_helper_allows_vm_count_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    monkeypatch.setattr(cli, "_check_command", lambda name: True)
    monkeypatch.setattr(cli, "_check_import", lambda name: True)

    called = {}

    def fake_run(cmd, check, env):
        called["cmd"] = cmd
        called["env"] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["test", "multipass", "--vm-count", "2"])
    assert result.exit_code == 0, result.output
    assert called["env"]["LB_MULTIPASS_VM_COUNT"] == "2"
    cmd = called.get("cmd")
    assert cmd is not None
    assert "tests/integration/test_multipass_benchmark.py" in cmd
    assert "VM count" in result.output
    assert "2 (multi-VM)" in result.output


def test_multipass_helper_runs_multi_workloads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    monkeypatch.setattr(cli, "_check_command", lambda name: True)
    monkeypatch.setattr(cli, "_check_import", lambda name: True)

    called = {}

    def fake_run(cmd, check, env):
        called["cmd"] = cmd
        called["env"] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = runner.invoke(
        cli.app,
        ["test", "multipass", "--multi-workloads", "--vm-count", "2", "--", "-k", "smoke"],
    )
    assert result.exit_code == 0, result.output
    assert called["env"]["LB_MULTIPASS_VM_COUNT"] == "2"
    cmd = called["cmd"]
    assert "tests/integration/test_multipass_multi_workloads.py" in cmd
    # extra args should pass through
    assert "-k" in cmd and "smoke" in cmd


def test_multipass_helper_accepts_pytest_flags_without_separator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    monkeypatch.setattr(cli, "_check_command", lambda name: True)
    monkeypatch.setattr(cli, "_check_import", lambda name: True)

    called = {}

    def fake_run(cmd, check, env):
        called["cmd"] = cmd
        called["env"] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["test", "multipass", "-v", "-s"])
    assert result.exit_code == 0, result.output
    cmd = called.get("cmd")
    assert cmd is not None
    assert "-v" in cmd and "-s" in cmd
