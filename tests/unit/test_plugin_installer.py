import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Type

import pytest

from linux_benchmark_lib.benchmark_config import BenchmarkConfig
from linux_benchmark_lib.services import plugin_service as plugin_service_mod
from linux_benchmark_lib.services.config_service import ConfigService
from linux_benchmark_lib.services.plugin_service import PluginInstaller, create_registry
from linux_benchmark_lib.plugins.interface import WorkloadPlugin
from linux_benchmark_lib.plugins.base_generator import BaseGenerator

# Dummy plugin content to be written to files
DUMMY_PLUGIN_CONTENT = """
from dataclasses import dataclass
from typing import Type
from linux_benchmark_lib.plugins.interface import WorkloadPlugin
from linux_benchmark_lib.plugins.base_generator import BaseGenerator

@dataclass
class DummyConfig:
    pass

class DummyGenerator(BaseGenerator):
    def __init__(self, config, name="Dummy"):
        super().__init__(name)

    def _validate_environment(self):
        return True
    
    def _run_command(self):
        pass
        
    def _stop_workload(self):
        pass

class DummyPlugin(WorkloadPlugin):
    @property
    def name(self) -> str:
        return "dummy"
    
    @property
    def description(self) -> str:
        return "Dummy plugin for testing"
        
    @property
    def config_cls(self) -> Type[DummyConfig]:
        return DummyConfig
        
    def create_generator(self, config):
        return DummyGenerator(config)

PLUGIN = DummyPlugin()
"""

@pytest.fixture
def dummy_plugin_path(tmp_path):
    """Create a dummy plugin directory structure."""
    plugin_dir = tmp_path / "dummy_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "dummy.py").write_text(DUMMY_PLUGIN_CONTENT)
    (plugin_dir / "__init__.py").write_text("")
    return plugin_dir

def _patch_plugin_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point user plugin dir to a temporary location."""
    plugin_dir = tmp_path / "plugins"
    monkeypatch.setattr(plugin_service_mod, "USER_PLUGIN_DIR", plugin_dir)
    monkeypatch.setattr(create_registry.__globals__['registry'], "USER_PLUGIN_DIR", plugin_dir)
    return plugin_dir

@pytest.mark.parametrize("source", ["archive", "directory"])
def test_installer_handles_archive_and_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_plugin_path: Path, source: str):
    """PluginInstaller should install plugins from both archives and directories."""
    plugin_dir = _patch_plugin_dir(monkeypatch, tmp_path)
    installer = PluginInstaller()

    if source == "archive":
        archive_path = installer.package(dummy_plugin_path, tmp_path / "dummy.tar.gz")
        install_source = archive_path
    else:
        install_source = dummy_plugin_path

    name = installer.install(install_source, force=True)
    assert name == "dummy"

    assert (plugin_dir / "dummy.py").exists()

    registry = create_registry()
    plugin = registry.get("dummy")
    assert plugin.name == "dummy"


def test_install_from_git_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_plugin_path: Path):
    """PluginInstaller should clone and install from a git repository URL."""
    if shutil.which("git") is None:
        pytest.skip("git is required for this test")

    plugin_dir = _patch_plugin_dir(monkeypatch, tmp_path)
    
    # Setup git repo
    source = tmp_path / "git_src"
    shutil.copytree(dummy_plugin_path, source)

    subprocess.run(["git", "init", "-b", "main"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=source,
        check=True,
        capture_output=True,
    )

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=remote, check=True, capture_output=True
    )
    subprocess.run(["git", "push", str(remote), "main"], cwd=source, check=True, capture_output=True)

    installer = PluginInstaller()
    name = installer.install(remote.as_uri(), force=True)
    assert name == "dummy"
    assert (plugin_dir / "dummy.py").exists()


def test_uninstall_and_config_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_plugin_path: Path):
    """Uninstall should remove files and ConfigService should purge config entries."""
    plugin_dir = _patch_plugin_dir(monkeypatch, tmp_path)
    installer = PluginInstaller()
    
    # Install first
    installer.install(dummy_plugin_path, force=True)

    cfg = BenchmarkConfig()
    config_path = tmp_path / "config.json"
    cfg.save(config_path)

    config_service = ConfigService(config_home=tmp_path)
    updated, target, _, removed = config_service.remove_plugin("dummy", config_path)
    assert removed is True
    assert target == config_path

    assert installer.uninstall("dummy") is True
    assert not (plugin_dir / "dummy.py").exists()
    assert installer.uninstall("dummy") is False
