from __future__ import annotations

from pathlib import Path

import pytest

from lb_plugins.plugins.sysbench.plugin import SysbenchConfig, SysbenchGenerator
from lb_plugins.plugins.stress_ng.plugin import StressNGConfig, StressNGGenerator
from lb_plugins.plugins.dd.plugin import DDConfig, DDGenerator
from lb_plugins.plugins.unixbench.plugin import UnixBenchConfig, UnixBenchGenerator

pytestmark = [pytest.mark.unit_plugins]


def test_stdout_command_generator_defaults() -> None:
    generator = SysbenchGenerator(SysbenchConfig())
    kwargs = generator._popen_kwargs()

    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    assert kwargs["text"] is True
    assert kwargs["bufsize"] == 1
    assert "cwd" not in kwargs


def test_stdout_command_generator_includes_workdir(tmp_path: Path) -> None:
    config = UnixBenchConfig(workdir=tmp_path)
    generator = UnixBenchGenerator(config)
    kwargs = generator._popen_kwargs()

    assert kwargs["cwd"] == tmp_path


def test_stress_ng_uses_stdout_command_defaults() -> None:
    generator = StressNGGenerator(StressNGConfig())
    kwargs = generator._popen_kwargs()

    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    assert kwargs["text"] is True


def test_dd_uses_custom_popen_kwargs() -> None:
    generator = DDGenerator(DDConfig())
    kwargs = generator._popen_kwargs()

    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    assert kwargs["text"] is True
