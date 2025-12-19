import os
from pathlib import Path

import pytest

from lb_runner.plugin_system.registry import PluginRegistry


def _write_plugin_file(path: Path, name: str) -> None:
    path.write_text(
        f"""
class DummyConfig: ...
class DummyPlugin:
    name = "{name}"
    config_cls = DummyConfig
    def create_generator(self, cfg): return ("gen", cfg)
PLUGIN = DummyPlugin()
"""
    )


def test_loads_top_level_user_plugin(tmp_path, monkeypatch):
    plugin_file = tmp_path / "my_plugin.py"
    _write_plugin_file(plugin_file, "my_plugin")
    monkeypatch.setenv("LB_USER_PLUGIN_DIR", str(tmp_path))

    registry = PluginRegistry([])

    plugin = registry.get("my_plugin")
    assert plugin.name == "my_plugin"


def test_loads_package_plugin_via_pyproject(tmp_path, monkeypatch):
    plugin_dir = tmp_path / "pkg_plugin"
    src_pkg = plugin_dir / "src" / "pkg_plugin"
    src_pkg.mkdir(parents=True)
    (plugin_dir / "pyproject.toml").write_text(
        '[project]\nname = "pkg-plugin"\nversion = "0.0.0"\n'
    )
    _write_plugin_file(src_pkg / "plugin.py", "pkg_plugin")
    monkeypatch.setenv("LB_USER_PLUGIN_DIR", str(tmp_path))

    registry = PluginRegistry([])

    plugin = registry.get("pkg_plugin")
    assert plugin.name == "pkg_plugin"
