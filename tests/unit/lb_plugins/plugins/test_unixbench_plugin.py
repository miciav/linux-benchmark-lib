import subprocess
from pathlib import Path

import pytest

from lb_plugins.api import (
    CommandGenerator,
    UnixBenchConfig,
    UnixBenchGenerator,
    UnixBenchPlugin,
)

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


def test_unixbench_parses_results_and_index() -> None:
    # Report tail of a real UnixBench 5.1.3 run captured from a Multipass VM.
    stdout = (
        "1 x Dhrystone 2 using register variables  1\n\n"
        "0 CPUs in system; running 1 parallel copy of tests\n\n"
        "Dhrystone 2 using register variables       77592446.5 lps   "
        "(10.0 s, 1 samples)\n\n"
        "System Benchmarks Partial Index              BASELINE       RESULT    INDEX\n"
        "Dhrystone 2 using register variables         116700.0   77592446.5   6648.9\n"
        "                                                                   ========\n"
        "System Benchmarks Index Score (Partial Only)                         6648.9\n"
    )
    gen = UnixBenchGenerator(UnixBenchConfig())
    assert gen._result_parser is not None
    result = gen._result_parser.parse({"stdout": stdout})
    assert result["dhrystone_2_using_register_variables_result"] == 77592446.5
    assert result["dhrystone_2_using_register_variables_unit"] == "lps"
    assert result["dhrystone_2_using_register_variables_index"] == 6648.9
    assert result["index_score"] == 6648.9
