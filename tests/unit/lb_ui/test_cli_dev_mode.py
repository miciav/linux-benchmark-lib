"""CLI dev-mode gating tests."""

from types import SimpleNamespace

from typer.testing import CliRunner

from lb_ui import cli

runner = CliRunner()


def test_run_docker_denied_when_not_dev(monkeypatch):
    monkeypatch.setattr(cli, "DEV_MODE", False)
    monkeypatch.setattr(cli, "ui", type("U", (), {"show_error": lambda self, msg: None})())  # suppress printing
    result = runner.invoke(cli.app, ["run", "--docker"])
    assert result.exit_code != 0


def test_run_multipass_vm_count_validation(monkeypatch):
    monkeypatch.setattr(cli, "DEV_MODE", True)
    result = runner.invoke(cli.app, ["run", "--multipass", "--multipass-vm-count", "0"])
    assert result.exit_code != 0


def test_run_docker_allowed_in_dev(monkeypatch):
    monkeypatch.setattr(cli, "DEV_MODE", True)

    class FakeRunService:
        def create_session(self, *args, **kwargs):
            return SimpleNamespace(
                config=cli.BenchmarkConfig(),
                target_tests=[],
                registry=None,
                use_container=True,
                use_multipass=False,
                use_remote=False,
            )

        def execute(self, *args, **kwargs):
            return type("R", (), {"journal_path": None, "log_path": None})()

    monkeypatch.setattr(cli, "run_service", FakeRunService())
    monkeypatch.setattr(cli, "_print_run_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli.config_service, "load_for_read", lambda path: (cli.BenchmarkConfig(), None, None))  # type: ignore[attr-defined]

    result = runner.invoke(cli.app, ["run", "--docker", "--no-setup"], catch_exceptions=False)
    assert result.exit_code == 0
