import subprocess
import pytest

import lb_runner.plugins.geekbench.plugin as gb_mod


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
    assert plugin.get_dockerfile_path() and plugin.get_dockerfile_path().exists()
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

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_tmpfile(delete=False):
        return FakeTmp(bad_tmp)

    def fake_run(cmd, check=False, capture_output=False, text=False):
        bad_tmp.write_text("<html>redirect</html>")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(gb_mod.tempfile, "NamedTemporaryFile", fake_tmpfile)
    monkeypatch.setattr(gb_mod.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="gzip"):
        gen._prepare_geekbench()
    assert not any(workdir.glob("Geekbench-*"))
