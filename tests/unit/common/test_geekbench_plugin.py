import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

import lb_plugins.plugins.geekbench.plugin as gb_mod

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]



def test_geekbench_defaults():
    cfg = gb_mod.GeekbenchConfig()
    plugin = gb_mod.PLUGIN
    assert plugin.name == "geekbench"
    assert plugin.description
    gen = plugin.create_generator(cfg)
    assert isinstance(gen, gb_mod.GeekbenchGenerator)
    assert cfg.version == "6.3.0"
    assert cfg.skip_cleanup is True
    assert cfg.extra_args == []
    assert cfg.arch_override is None


def test_geekbench_required_packages_and_paths():
    plugin = gb_mod.PLUGIN
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

    cfg = gb_mod.GeekbenchConfig(
        output_dir=output_dir,
        workdir=workdir,
        license_key="ABC-123",
        run_gpu=True,
        extra_args=["--foo"],
        skip_cleanup=False,
        debug=True,
    )
    gen = gb_mod.GeekbenchGenerator(cfg)

    monkeypatch.setattr(gen, "_validate_environment", lambda: True)
    monkeypatch.setattr(gb_mod.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(gen, "_prepare_geekbench", lambda: (exec_path, archive_path, exec_path.parent))

    calls: list[list[str]] = []
    def fake_exec(cmd, env=None, cwd=None):
        calls.append(cmd)
        # Simulate Geekbench creating the JSON export when requested.
        if "--export-json" in cmd:
            idx = cmd.index("--export-json")
            if idx + 1 < len(cmd):
                Path(cmd[idx + 1]).write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(gen, "_execute_process", fake_exec)

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

def test_geekbench_load_config_from_file_merges_common_and_plugin(tmp_path: Path) -> None:
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
    cfg = gb_mod.PLUGIN.load_config_from_file(cfg_path)
    assert isinstance(cfg, gb_mod.GeekbenchConfig)
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
    cfg = gb_mod.PLUGIN.load_config_from_file(cfg_path)
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
        gb_mod.PLUGIN.load_config_from_file(cfg_path)


def test_geekbench_download_detects_bad_archive(monkeypatch, tmp_path):
    """A non-gzip download should raise and not leave artifacts behind."""
    workdir = tmp_path / "work"
    cfg = gb_mod.GeekbenchConfig(workdir=workdir)
    gen = gb_mod.GeekbenchGenerator(cfg)

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

    monkeypatch.setattr(gb_mod.tempfile, "NamedTemporaryFile", fake_tmpfile)
    monkeypatch.setattr(gb_mod.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="gzip"):
        gen._prepare_geekbench()
    assert not any(workdir.glob("Geekbench-*"))
