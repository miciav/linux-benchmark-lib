"""Optional unit tests for external user plugins cloned into `_user/`.

These tests are skipped unless the external plugins are present locally.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from lb_runner.plugin_system.builtin import builtin_plugins
from lb_runner.plugin_system.interface import BasePluginConfig
from lb_runner.plugin_system.registry import PluginRegistry, USER_PLUGIN_DIR

pytestmark = pytest.mark.runner


def _has_external(name: str) -> bool:
    return (USER_PLUGIN_DIR / name).exists()


def test_sysbench_user_plugin_yaml_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not _has_external("sysbench-plugin"):
        pytest.skip("external sysbench-plugin not present")

    # Ensure we load only from `_user/` and do not get overridden by legacy plugins.
    monkeypatch.setenv("LB_USER_PLUGIN_DIR", str(USER_PLUGIN_DIR))

    registry = PluginRegistry(builtin_plugins())
    plugin = registry.get("sysbench")
    assert issubclass(plugin.config_cls, BaseModel)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
common:
  max_retries: 2
  tags: ["common"]
plugins:
  sysbench:
    threads: 4
    time: 5
    cpu_max_prime: 25000
""".lstrip()
    )

    cfg = plugin.load_config_from_file(cfg_path)
    assert isinstance(cfg, BasePluginConfig)
    assert cfg.max_retries == 2
    assert cfg.tags == ["common"]
    assert getattr(cfg, "threads") == 4


def test_unixbench_user_plugin_yaml_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not _has_external("unixbench-plugin"):
        pytest.skip("external unixbench-plugin not present")

    monkeypatch.setenv("LB_USER_PLUGIN_DIR", str(USER_PLUGIN_DIR))

    registry = PluginRegistry(builtin_plugins())
    plugin = registry.get("unixbench")
    assert issubclass(plugin.config_cls, BaseModel)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
common:
  tags: ["t1"]
plugins:
  unixbench:
    threads: 2
    iterations: 1
    workdir: "./UnixBench"
""".lstrip()
    )

    cfg = plugin.load_config_from_file(cfg_path)
    assert isinstance(cfg, BasePluginConfig)
    assert cfg.tags == ["t1"]
    assert getattr(cfg, "threads") == 2
    assert getattr(cfg, "workdir") == Path("./UnixBench")


def test_unixbench_user_plugin_yaml_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not _has_external("unixbench-plugin"):
        pytest.skip("external unixbench-plugin not present")

    monkeypatch.setenv("LB_USER_PLUGIN_DIR", str(USER_PLUGIN_DIR))

    registry = PluginRegistry(builtin_plugins())
    plugin = registry.get("unixbench")

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
plugins:
  unixbench:
    threads: 0
""".lstrip()
    )

    with pytest.raises(ValidationError):
        plugin.load_config_from_file(cfg_path)
