import subprocess

import pytest

from lb_plugins.api import (
    CommandGenerator,
    SysbenchConfig,
    SysbenchGenerator,
    SysbenchPlugin,
)

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

    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/sysbench" if name == "sysbench" else None
    )
    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = SysbenchConfig()
    gen = SysbenchGenerator(cfg)
    assert gen._validate_environment() is True
    assert calls and calls[0][:2] == ["sysbench", "--version"]


def test_sysbench_parses_summary_and_latency() -> None:
    # Tail of real sysbench 1.0.20 cpu output captured from a Multipass run.
    stdout = (
        "CPU speed:\n"
        "    events per second:  4040.35\n\n"
        "General statistics:\n"
        "    total time:                          15.0004s\n"
        "    total number of events:              60616\n\n"
        "Latency (ms):\n"
        "         min:                                    0.49\n"
        "         avg:                                    0.49\n"
        "         max:                                    0.85\n"
        "         95th percentile:                        0.50\n"
        "         sum:                                29988.49\n"
    )
    gen = SysbenchGenerator(SysbenchConfig())
    assert gen._result_parser is not None
    result = gen._result_parser.parse({"stdout": stdout})
    assert result["events_per_second"] == 4040.35
    assert result["total_time_seconds"] == 15.0004
    assert result["total_events"] == 60616.0
    assert result["latency_max_ms"] == 0.85
    assert result["latency_p95_ms"] == 0.50
    assert result["latency_sum_ms"] == 29988.49
