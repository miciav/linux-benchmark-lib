import platform
import subprocess
import tempfile
from pathlib import Path

import pytest

from lb_plugins.api import CommandGenerator, DDConfig, DDGenerator, DDPlugin

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]


def test_dd_defaults() -> None:
    cfg = DDConfig()
    plugin = DDPlugin()
    assert plugin.name == "dd"
    assert plugin.description
    gen = plugin.create_generator(cfg)
    assert isinstance(gen, DDGenerator)
    assert isinstance(gen, CommandGenerator)


def test_dd_build_command_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    cfg = DDConfig(count=5, conv="fdatasync", oflag="direct")
    cmd = DDGenerator(cfg)._build_command()
    assert "if=/dev/zero" in cmd
    assert f"of={cfg.of_path}" in cmd
    output_path = Path(cfg.of_path)
    assert output_path.is_relative_to(Path(tempfile.gettempdir()))
    assert "count=5" in cmd
    assert "conv=fdatasync" in cmd
    assert "oflag=direct" in cmd
    assert "status=progress" in cmd


def test_dd_build_command_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    cfg = DDConfig(count=1, conv="fdatasync", oflag="direct")
    cmd = DDGenerator(cfg)._build_command()
    assert "count=1" in cmd
    assert "conv=sync" in cmd
    assert not any(part.startswith("oflag=") for part in cmd)


def test_dd_popen_kwargs() -> None:
    cfg = DDConfig()
    gen = DDGenerator(cfg)
    kwargs = gen._popen_kwargs()
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.PIPE
    assert kwargs["text"] is True
