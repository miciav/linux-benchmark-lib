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

from lb_runner.benchmark_config import RemoteHostConfig
from lb_runner.plugin_system.interface import WorkloadPlugin

if TYPE_CHECKING:
    from ..controller import AnsibleRunnerExecutor, InventorySpec

logger = logging.getLogger(__name__)

# Assuming standard layout: lb_controller/ansible/playbooks
ANSIBLE_ROOT = Path(__file__).resolve().parent.parent / "ansible"


class SetupService:
    """Manages environment provisioning via Ansible."""

    def __init__(self, executor: Optional["AnsibleRunnerExecutor"] = None):
        from ..controller import AnsibleRunnerExecutor, InventorySpec

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
        self, target_hosts: Optional[List[RemoteHostConfig]] = None
    ) -> bool:
        """
        Run the global setup playbook (dependencies, base directories).

        If target_hosts is None, runs against localhost.
        """
        playbook = ANSIBLE_ROOT / "playbooks" / "setup.yml"
        if not playbook.exists():
            logger.warning(f"Global setup playbook not found at {playbook}")
            return False

        inventory = (
            self._inventory_cls(hosts=target_hosts)
            if target_hosts
            else self._get_local_inventory()
        )

        logger.info("Running global setup...")
        result = self.executor.run_playbook(
            playbook,
            inventory=inventory,
            extravars={"lb_workdir": "/opt/lb"},  # Default global workdir
        )
        return result.success

    def provision_workload(
        self,
        plugin: WorkloadPlugin,
        target_hosts: Optional[List[RemoteHostConfig]] = None,
    ) -> bool:
        """
        Run the setup playbook for a specific workload plugin.
        """
        playbook = plugin.get_ansible_setup_path()
        if not playbook:
            logger.debug(f"No setup playbook for plugin {plugin.name}")
            return True

        inventory = (
            self._inventory_cls(hosts=target_hosts)
            if target_hosts
            else self._get_local_inventory()
        )

        extravars: Dict[str, Any] = {}
        try:
            extravars.update(plugin.get_ansible_setup_extravars())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "Failed to compute setup extravars for %s: %s", plugin.name, exc
            )

        logger.info(f"Running setup for {plugin.name}...")
        result = self.executor.run_playbook(
            playbook, inventory=inventory, extravars=extravars or None
        )
        return result.success

    def teardown_workload(
        self,
        plugin: WorkloadPlugin,
        target_hosts: Optional[List[RemoteHostConfig]] = None,
    ) -> bool:
        """
        Run the teardown playbook for a specific workload plugin.
        """
        playbook = plugin.get_ansible_teardown_path()
        if not playbook:
            return True

        inventory = (
            self._inventory_cls(hosts=target_hosts)
            if target_hosts
            else self._get_local_inventory()
        )

        extravars: Dict[str, Any] = {}
        try:
            extravars.update(plugin.get_ansible_teardown_extravars())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "Failed to compute teardown extravars for %s: %s", plugin.name, exc
            )

        logger.info(f"Running teardown for {plugin.name}...")
        result = self.executor.run_playbook(
            playbook,
            inventory=inventory,
            extravars=extravars or None,
            cancellable=False,
        )
        return result.success

    def teardown_global(
        self, target_hosts: Optional[List[RemoteHostConfig]] = None
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

        logger.info("Running global teardown...")
        result = self.executor.run_playbook(
            playbook, inventory=inventory, cancellable=False
        )
        return result.success
