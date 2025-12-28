import subprocess

import pytest

from lb_plugins.api import CommandGenerator, StressNGConfig, StressNGGenerator, StressNGPlugin

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]


def test_stress_ng_defaults() -> None:
    cfg = StressNGConfig()
    plugin = StressNGPlugin()
    assert plugin.name == "stress_ng"
    assert plugin.description
    gen = plugin.create_generator(cfg)
    assert isinstance(gen, StressNGGenerator)
    assert isinstance(gen, CommandGenerator)


def test_stress_ng_build_command() -> None:
    cfg = StressNGConfig(
        cpu_workers=2,
        cpu_method="matrixprod",
        vm_workers=1,
        vm_bytes="256M",
        io_workers=1,
        timeout=30,
        metrics_brief=True,
        extra_args=["--cpu-load", "50"],
        debug=True,
    )
    cmd = StressNGGenerator(cfg)._build_command()
    assert cmd[:1] == ["stress-ng"]
    assert "--cpu" in cmd and "2" in cmd
    assert "--cpu-method" in cmd and "matrixprod" in cmd
    assert "--vm" in cmd and "1" in cmd
    assert "--vm-bytes" in cmd and "256M" in cmd
    assert "--io" in cmd and "1" in cmd
    assert "--timeout" in cmd and "30s" in cmd
    assert "--metrics-brief" in cmd
    assert "--verbose" in cmd
    assert "--cpu-load" in cmd and "50" in cmd


def test_stress_ng_popen_kwargs() -> None:
    cfg = StressNGConfig()
    gen = StressNGGenerator(cfg)
    kwargs = gen._popen_kwargs()
    assert kwargs["stdout"] == subprocess.PIPE
    assert kwargs["stderr"] == subprocess.STDOUT
    assert kwargs["text"] is True
    assert kwargs["bufsize"] == 1
