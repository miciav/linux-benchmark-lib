import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from benchmark_config import BenchmarkConfig


def _load_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import the CLI module with an isolated config home and cwd."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    if "cli" in sys.modules:
        del sys.modules["cli"]
    cli = importlib.import_module("cli")
    importlib.reload(cli)
    return cli


def test_plugins_enable_disable_persists_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()
    config_path = tmp_path / "cfg.json"

    result = runner.invoke(cli.app, ["plugins", "--enable", "stress_ng", "-c", str(config_path)])
    assert result.exit_code == 0, result.output

    cfg = BenchmarkConfig.load(config_path)
    assert "stress_ng" in cfg.workloads
    assert cfg.workloads["stress_ng"].enabled is True

    result = runner.invoke(cli.app, ["plugins", "--disable", "stress_ng", "-c", str(config_path)])
    assert result.exit_code == 0, result.output

    cfg = BenchmarkConfig.load(config_path)
    assert cfg.workloads["stress_ng"].enabled is False


def test_plugins_shows_enabled_column(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["plugins"])
    assert result.exit_code == 0, result.output
    # Check that the table includes the Enabled column and a known plugin name
    assert "Enabled" in result.output
    assert "stress_ng" in result.output


def test_doctor_controller_uses_checks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    monkeypatch.setattr(cli, "_check_import", lambda name: True)
    monkeypatch.setattr(cli, "_check_command", lambda name: True)

    result = runner.invoke(cli.app, ["doctor", "controller"])
    assert result.exit_code == 0, result.output


def test_doctor_local_tools_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()
    monkeypatch.setattr(cli, "_check_command", lambda name: False)
    result = runner.invoke(cli.app, ["doctor", "local-tools"])
    assert result.exit_code != 0


def test_plugins_conflicting_flags_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["plugins", "--enable", "a", "--disable", "b"])
    assert result.exit_code != 0


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
    assert "yes" in result.output


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
    cmd = called.get("cmd")
    assert cmd is not None
    assert cmd[0] == sys.executable
    assert "pytest" in cmd
