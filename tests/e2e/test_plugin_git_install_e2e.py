"""E2E test for installing a workload plugin from a git URL.

This test is network-dependent and is skipped unless the environment provides
`LB_E2E_GIT_PLUGIN_URL`. It verifies that:
1) PluginInstaller installs from the given git URL.
2) The installed plugin appears in the available plugin list.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lb_controller.api import PluginInstaller, create_registry
from lb_controller.services import plugin_service as plugin_service_mod

pytestmark = [pytest.mark.e2e, pytest.mark.integration, pytest.mark.plugins, pytest.mark.slow]

DEFAULT_E2E_GIT_PLUGIN_URL = "https://github.com/miciav/sysbench-plugin.git"


def _patch_plugin_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point user plugin dir to a temporary location."""
    plugin_dir = tmp_path / "plugins"
    monkeypatch.setattr(plugin_service_mod, "USER_PLUGIN_DIR", plugin_dir)
    import lb_runner.plugin_system.registry as registry_mod

    monkeypatch.setattr(registry_mod, "USER_PLUGIN_DIR", plugin_dir)
    monkeypatch.setattr(create_registry.__globals__["registry"], "USER_PLUGIN_DIR", plugin_dir)
    plugin_dir.mkdir(parents=True, exist_ok=True)
    return plugin_dir


def test_e2e_install_plugin_from_git_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Install a plugin from git and ensure it is discoverable."""
    url = DEFAULT_E2E_GIT_PLUGIN_URL
    if shutil.which("git") is None:
        pytest.skip("git is required for this test")
    # Skip safely when network access to GitHub is unavailable.
    try:
        probe = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if probe.returncode != 0:
            pytest.skip(f"Network unavailable for git probe: {probe.stderr.strip() or probe.stdout.strip()}")
    except Exception as exc:
        pytest.skip(f"Network unavailable for git probe: {exc}")

    _patch_plugin_dir(monkeypatch, tmp_path)
    # Ensure any cached registry doesn't mask changes.
    plugin_service_mod._REGISTRY_CACHE = None

    baseline_registry = create_registry(refresh=True)
    baseline_plugins = set(baseline_registry.available(load_entrypoints=True).keys())
    baseline_has_sysbench = "sysbench" in baseline_plugins

    installer = PluginInstaller()
    installed_name: str | None = None
    main_exc: BaseException | None = None
    try:
        installed_name = installer.install(url, force=True)

        plugin_service_mod._REGISTRY_CACHE = None
        new_registry = create_registry(refresh=True)
        new_plugins = set(new_registry.available(load_entrypoints=True).keys())

        # The sysbench plugin should be available after install.
        assert "sysbench" in new_plugins, f"'sysbench' plugin not discoverable after installing from {url}"

        # If sysbench wasn't already installed in the environment, we expect a new plugin to appear.
        if not baseline_has_sysbench:
            diff = new_plugins - baseline_plugins
            assert diff, f"No new plugins discovered after installing from {url}"
    except BaseException as exc:  # ensure cleanup still runs
        main_exc = exc
    finally:
        # Ensure the installed plugin is removed from the user plugin dir after the test,
        # using the real uninstall path so it is exercised by this e2e.
        uninstall_ok = True
        if installed_name:
            try:
                uninstall_ok = installer.uninstall(installed_name) and uninstall_ok
            except Exception:
                uninstall_ok = False
        # Best-effort cleanup by entry-point name as well.
        try:
            installer.uninstall("sysbench")
        except Exception:
            uninstall_ok = False

        if main_exc is None:
            assert uninstall_ok, "Plugin uninstall failed during e2e cleanup"
        else:
            raise main_exc
