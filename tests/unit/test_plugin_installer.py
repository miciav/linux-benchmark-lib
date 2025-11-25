import shutil
import subprocess
from pathlib import Path

import pytest

from benchmark_config import BenchmarkConfig
from services import plugin_service as plugin_service_mod
from services.config_service import ConfigService
from services.plugin_service import PluginInstaller, create_registry
from plugins import registry as registry_mod
from workload_generators.sysbench_generator import SysbenchGenerator

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "plugins" / "packages" / "sysbench_plugin"
ARCHIVE_ROOT = REPO_ROOT / "plugins" / "packages" / "sysbench_plugin.tar.gz"


def _patch_plugin_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point user plugin dir to a temporary location."""
    plugin_dir = tmp_path / "plugins"
    monkeypatch.setattr(plugin_service_mod, "USER_PLUGIN_DIR", plugin_dir)
    monkeypatch.setattr(registry_mod, "USER_PLUGIN_DIR", plugin_dir)
    return plugin_dir


@pytest.mark.parametrize("source", ["archive", "directory"])
def test_installer_handles_archive_and_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str):
    """PluginInstaller should install plugins from both archives and directories."""
    plugin_dir = _patch_plugin_dir(monkeypatch, tmp_path)
    installer = PluginInstaller()

    if source == "archive":
        archive_path = installer.package(PACKAGE_ROOT, tmp_path / "sysbench.tar.gz")
        install_source = archive_path
    else:
        install_source = PACKAGE_ROOT

    name = installer.install(install_source, force=True)
    assert name == "sysbench"

    assert (plugin_dir / "sysbench.py").exists()
    assert (plugin_dir / "sysbench.yaml").exists()

    registry = create_registry()
    plugin = registry.get("sysbench")
    generator = registry.create_generator("sysbench", {})
    assert plugin.name == "sysbench"
    assert isinstance(generator, SysbenchGenerator)


def test_install_from_compressed_export(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Ensure pre-compressed plugin exports can be installed directly."""
    plugin_dir = _patch_plugin_dir(monkeypatch, tmp_path)
    installer = PluginInstaller()

    assert ARCHIVE_ROOT.exists()
    name = installer.install(ARCHIVE_ROOT, force=True)
    assert name == "sysbench"
    assert (plugin_dir / "sysbench.py").exists()
    assert (plugin_dir / "sysbench.yaml").exists()

    registry = create_registry()
    assert "sysbench" in registry.available()


def test_install_from_git_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """PluginInstaller should clone and install from a git repository URL."""
    if shutil.which("git") is None:
        pytest.skip("git is required for this test")

    plugin_dir = _patch_plugin_dir(monkeypatch, tmp_path)
    source = tmp_path / "git_src"
    shutil.copytree(PACKAGE_ROOT, source)

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
    assert name == "sysbench"
    assert (plugin_dir / "sysbench.py").exists()
    assert (plugin_dir / "sysbench.yaml").exists()


def test_uninstall_and_config_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Uninstall should remove files and ConfigService should purge config entries."""
    plugin_dir = _patch_plugin_dir(monkeypatch, tmp_path)
    installer = PluginInstaller()
    archive_path = installer.package(PACKAGE_ROOT, tmp_path / "sysbench.tar.gz")
    installer.install(archive_path, force=True)

    cfg = BenchmarkConfig()
    config_path = tmp_path / "config.json"
    cfg.save(config_path)

    config_service = ConfigService(config_home=tmp_path)
    updated, target, _, removed = config_service.remove_plugin("sysbench", config_path)
    assert removed is True
    assert "sysbench" not in updated.workloads
    assert "sysbench" not in updated.plugin_settings
    assert target == config_path

    assert installer.uninstall("sysbench") is True
    assert not (plugin_dir / "sysbench.py").exists()
    assert not (plugin_dir / "sysbench.yaml").exists()
    assert installer.uninstall("sysbench") is False
