import platform
import subprocess
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from lb_plugins.api import GeekbenchConfig, GeekbenchGenerator, GeekbenchPlugin

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]


def test_geekbench_defaults():
    cfg = GeekbenchConfig()
    plugin = GeekbenchPlugin()
    assert plugin.name == "geekbench"
    assert plugin.description
    gen = plugin.create_generator(cfg)
    assert isinstance(gen, GeekbenchGenerator)
    assert cfg.version == "6.3.0"
    assert cfg.skip_cleanup is True
    assert cfg.extra_args == []
    assert cfg.arch_override is None


def test_geekbench_required_packages_and_paths():
    plugin = GeekbenchPlugin()
    pkgs = plugin.get_required_apt_packages()
    for pkg in ("curl", "wget", "tar", "ca-certificates", "sysstat"):
        assert pkg in pkgs
    tools = plugin.get_required_local_tools()
    assert "curl" in tools and "tar" in tools
    assert plugin.get_ansible_setup_path() and plugin.get_ansible_setup_path().exists()


def test_geekbench_generator_builds_command(monkeypatch, tmp_path):
    output_dir = tmp_path / "out"
    workdir = tmp_path / "work"
    output_dir.mkdir(parents=True, exist_ok=True)
    exec_path = workdir / "Geekbench-6.3.0-Linux" / "geekbench6_compute"
    exec_path.parent.mkdir(parents=True, exist_ok=True)
    exec_path.write_text("#!/bin/bash\necho ok\n")
    exec_path.chmod(0o755)
    archive_path = workdir / "Geekbench-6.3.0-Linux.tar.gz"
    archive_path.touch()

    cfg = GeekbenchConfig(
        output_dir=output_dir,
        workdir=workdir,
        license_key="ABC-123",
        run_gpu=True,
        extra_args=["--foo"],
        skip_cleanup=False,
        debug=True,
    )
    gen = GeekbenchGenerator(cfg)

    monkeypatch.setattr(gen, "_validate_environment", lambda: True)
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        gen, "_prepare_geekbench", lambda: (exec_path, archive_path, exec_path.parent)
    )

    calls: list[list[str]] = []

    class DummyProcess:
        def __init__(self, cmd, **_kwargs):
            self.cmd = cmd
            self.returncode = 0
            calls.append(cmd)

        def communicate(self, timeout=None):
            if "--export-json" in self.cmd:
                idx = self.cmd.index("--export-json")
                if idx + 1 < len(self.cmd):
                    Path(self.cmd[idx + 1]).write_text("{}", encoding="utf-8")
            return "ok", ""

    monkeypatch.setattr(subprocess, "Popen", DummyProcess)

    gen._run_command()

    assert calls, "Geekbench command was not invoked"
    cmd = calls[0]
    assert str(exec_path) == cmd[0]
    assert "--unlock" in cmd and "ABC-123" in cmd
    assert "--compute" in cmd
    assert "--export-json" in cmd
    assert "--foo" in cmd

    result = gen.get_result()
    assert result["returncode"] == 0
    assert not archive_path.exists()
    assert not exec_path.parent.exists()


def test_geekbench_load_config_from_file_merges_common_and_plugin(
    tmp_path: Path,
) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
common:
  max_retries: 2
  tags: ["common"]
plugins:
  geekbench:
    run_gpu: true
    version: "6.3.0"
    output_dir: "./out"
    extra_args: ["--foo"]
""".lstrip()
    )
    cfg = GeekbenchPlugin().load_config_from_file(cfg_path)
    assert isinstance(cfg, GeekbenchConfig)
    assert cfg.max_retries == 2
    assert cfg.tags == ["common"]
    assert cfg.run_gpu is True
    assert cfg.version == "6.3.0"
    assert cfg.output_dir == Path("./out")
    assert cfg.extra_args == ["--foo"]


def test_geekbench_load_config_from_file_ignores_unknown_fields(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
common:
  max_retries: 1
  totally_unknown: 123
plugins:
  geekbench:
    also_unknown: "x"
""".lstrip()
    )
    cfg = GeekbenchPlugin().load_config_from_file(cfg_path)
    assert cfg.max_retries == 1


def test_geekbench_load_config_from_file_invalid_data_raises(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
plugins:
  geekbench:
    expected_runtime_seconds: 0
""".lstrip()
    )
    with pytest.raises(ValidationError):
        GeekbenchPlugin().load_config_from_file(cfg_path)


def test_geekbench_download_detects_bad_archive(monkeypatch, tmp_path):
    """A non-gzip download should raise and not leave artifacts behind."""
    workdir = tmp_path / "work"
    cfg = GeekbenchConfig(workdir=workdir)
    gen = GeekbenchGenerator(cfg)

    bad_tmp = tmp_path / "fake_download"

    class FakeTmp:
        def __init__(self, name):
            self.name = str(name)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_tmpfile(*_args, **_kwargs):
        return FakeTmp(bad_tmp)

    def fake_run(cmd, **_kwargs):
        bad_tmp.write_text("<html>redirect</html>")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", fake_tmpfile)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="gzip"):
        gen._prepare_geekbench()
    assert not any(workdir.glob("Geekbench-*"))
