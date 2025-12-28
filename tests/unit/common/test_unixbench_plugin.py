from pathlib import Path
import subprocess

import pytest

from lb_plugins.api import CommandGenerator, UnixBenchConfig, UnixBenchGenerator, UnixBenchPlugin

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]


def test_unixbench_defaults() -> None:
    cfg = UnixBenchConfig()
    plugin = UnixBenchPlugin()
    assert plugin.name == "unixbench"
    assert plugin.description
    gen = plugin.create_generator(cfg)
    assert isinstance(gen, UnixBenchGenerator)
    assert isinstance(gen, CommandGenerator)
    assert cfg.threads == 1
    assert cfg.iterations == 1


def test_unixbench_paths_exist() -> None:
    plugin = UnixBenchPlugin()
    setup = plugin.get_ansible_setup_path()
    assert setup and setup.exists()


def test_unixbench_build_command_includes_tests_and_args() -> None:
    cfg = UnixBenchConfig(
        threads=2,
        iterations=3,
        tests=["dhry2reg", "whetstone-double"],
        extra_args=["--foo"],
        debug=True,
    )
    cmd = UnixBenchGenerator(cfg)._build_command()
    assert cmd == [
        "./Run",
        "-c",
        "2",
        "-i",
        "3",
        "dhry2reg",
        "whetstone-double",
        "--verbose",
        "--foo",
    ]


def test_unixbench_generator_timeout_and_popen_kwargs(tmp_path: Path) -> None:
    cfg = UnixBenchConfig(workdir=tmp_path, iterations=2, timeout_buffer=5)
    gen = UnixBenchGenerator(cfg)
    assert gen._timeout_seconds() == 125
    kwargs = gen._popen_kwargs()
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stderr"] == subprocess.STDOUT


def test_unixbench_validate_environment(tmp_path: Path) -> None:
    workdir = tmp_path / "UnixBench"
    workdir.mkdir()
    run_file = workdir / "Run"
    run_file.write_text("#!/bin/sh\necho ok\n")
    run_file.chmod(0o755)

    cfg = UnixBenchConfig(workdir=workdir)
    gen = UnixBenchGenerator(cfg)
    assert gen._validate_environment() is True


def test_unixbench_validate_environment_missing(tmp_path: Path) -> None:
    cfg = UnixBenchConfig(workdir=tmp_path / "missing")
    gen = UnixBenchGenerator(cfg)
    assert gen._validate_environment() is False
