import subprocess

import pytest

from lb_plugins.api import CommandGenerator, SysbenchConfig, SysbenchGenerator, SysbenchPlugin

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]


def test_sysbench_defaults() -> None:
    cfg = SysbenchConfig()
    plugin = SysbenchPlugin()
    assert plugin.name == "sysbench"
    assert plugin.description
    gen = plugin.create_generator(cfg)
    assert isinstance(gen, SysbenchGenerator)
    assert isinstance(gen, CommandGenerator)
    assert cfg.time == 60
    assert cfg.test == "cpu"


def test_sysbench_paths_exist() -> None:
    plugin = SysbenchPlugin()
    setup = plugin.get_ansible_setup_path()
    assert setup and setup.exists()


def test_sysbench_generator_builds_command() -> None:
    cfg = SysbenchConfig(
        test="cpu",
        threads=4,
        time=10,
        max_requests=500,
        rate=100,
        cpu_max_prime=12345,
        extra_args=["--foo", "bar"],
        debug=True,
    )
    cmd = SysbenchGenerator(cfg)._build_command()
    assert cmd == [
        "sysbench",
        "cpu",
        "--threads=4",
        "--time=10",
        "--events=500",
        "--rate=100",
        "--cpu-max-prime=12345",
        "--verbosity=3",
        "--foo",
        "bar",
        "run",
    ]


def test_sysbench_generator_timeout_and_popen_kwargs() -> None:
    cfg = SysbenchConfig(time=12, timeout_buffer=5)
    gen = SysbenchGenerator(cfg)
    assert gen._timeout_seconds() == 17
    kwargs = gen._popen_kwargs()
    assert kwargs["stderr"] == subprocess.STDOUT
    assert kwargs["bufsize"] == 1


def test_sysbench_validate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/sysbench" if name == "sysbench" else None)
    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = SysbenchConfig()
    gen = SysbenchGenerator(cfg)
    assert gen._validate_environment() is True
    assert calls and calls[0][:2] == ["sysbench", "--version"]
