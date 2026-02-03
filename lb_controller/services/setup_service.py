"""
Service for provisioning execution environments (local or remote).

This service bridges the gap between Python logic and Ansible playbooks,
allowing the CLI to prepare environments consistently.
"""

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

from lb_plugins.api import PluginAssetConfig
from lb_runner.api import DEFAULT_LB_WORKDIR, RemoteHostConfig

if TYPE_CHECKING:
    from lb_controller.api import AnsibleRunnerExecutor, InventorySpec

logger = logging.getLogger(__name__)
install_logger = logging.LoggerAdapter(logger, {"lb_phase": "install"})
teardown_logger = logging.LoggerAdapter(logger, {"lb_phase": "teardown"})

# Assuming standard layout: lb_controller/ansible/playbooks
ANSIBLE_ROOT = Path(__file__).resolve().parent.parent / "ansible"


class SetupService:
    """Manages environment provisioning via Ansible."""

    def __init__(self, executor: Optional["AnsibleRunnerExecutor"] = None):
        from lb_controller.api import AnsibleRunnerExecutor, InventorySpec

        self._inventory_cls: Type["InventorySpec"] = InventorySpec
        self.executor = executor or AnsibleRunnerExecutor(stream_output=True)

    def _get_local_inventory(self) -> "InventorySpec":
        """Create an ephemeral inventory for localhost."""
        # We use a dummy RemoteHostConfig that maps to localhost with local connection
        localhost = RemoteHostConfig(
            name="localhost",
            address="127.0.0.1",
            user=os.environ.get("USER", "root"),
            become=True,  # Typically setup requires sudo
            vars={
                "ansible_connection": "local",
                "ansible_python_interpreter": sys.executable,
            },
        )
        return self._inventory_cls(hosts=[localhost])

    def provision_global(
        self,
        target_hosts: Optional[List[RemoteHostConfig]] = None,
        lb_workdir: Optional[str] = None,
    ) -> bool:
        """
        Run the global setup playbook (dependencies, base directories).

        If target_hosts is None, runs against localhost.
        """
        playbook = ANSIBLE_ROOT / "playbooks" / "setup.yml"
        if not playbook.exists():
            install_logger.warning("Global setup playbook not found at %s", playbook)
            return False

        inventory = (
            self._inventory_cls(hosts=target_hosts)
            if target_hosts
            else self._get_local_inventory()
        )

        install_logger.info("Running global setup...")
        workdir = lb_workdir or DEFAULT_LB_WORKDIR
        result = self.executor.run_playbook(
            playbook,
            inventory=inventory,
            extravars={"lb_workdir": workdir},
        )
        return result.success

    def provision_workload(
        self,
        plugin_assets: PluginAssetConfig | None,
        plugin_name: str,
        target_hosts: Optional[List[RemoteHostConfig]] = None,
    ) -> bool:
        """
        Run the setup playbook for a specific workload plugin.
        """
        playbook = plugin_assets.setup_playbook if plugin_assets else None
        if not playbook:
            install_logger.debug("No setup playbook for plugin %s", plugin_name)
            return True

        inventory = (
            self._inventory_cls(hosts=target_hosts)
            if target_hosts
            else self._get_local_inventory()
        )

        extravars: Dict[str, Any] = {}
        if plugin_assets:
            extravars.update(plugin_assets.setup_extravars)

        install_logger.info("Running setup for %s...", plugin_name)
        result = self.executor.run_playbook(
            playbook, inventory=inventory, extravars=extravars or None
        )
        return result.success

    def teardown_workload(
        self,
        plugin_assets: PluginAssetConfig | None,
        plugin_name: str,
        target_hosts: Optional[List[RemoteHostConfig]] = None,
    ) -> bool:
        """
        Run the teardown playbook for a specific workload plugin.
        """
        playbook = plugin_assets.teardown_playbook if plugin_assets else None
        if not playbook:
            return True

        inventory = (
            self._inventory_cls(hosts=target_hosts)
            if target_hosts
            else self._get_local_inventory()
        )

        extravars: Dict[str, Any] = {}
        if plugin_assets:
            extravars.update(plugin_assets.teardown_extravars)

        teardown_logger.info("Running teardown for %s...", plugin_name)
        result = self.executor.run_playbook(
            playbook,
            inventory=inventory,
            extravars=extravars or None,
            cancellable=False,
        )
        return result.success

    def teardown_global(
        self,
        target_hosts: Optional[List[RemoteHostConfig]] = None,
        lb_workdir: Optional[str] = None,
    ) -> bool:
        """
        Run the global teardown playbook.
        """
        playbook = ANSIBLE_ROOT / "playbooks" / "teardown.yml"
        if not playbook.exists():
            return True

        inventory = (
            self._inventory_cls(hosts=target_hosts)
            if target_hosts
            else self._get_local_inventory()
        )

        teardown_logger.info("Running global teardown...")
        workdir = lb_workdir or DEFAULT_LB_WORKDIR
        result = self.executor.run_playbook(
            playbook,
            inventory=inventory,
            extravars={"lb_workdir": workdir},
            cancellable=False,
        )
        return result.success
