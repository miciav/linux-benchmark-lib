"""Workflow for interactive configuration."""

from __future__ import annotations

from lb_app.api import BenchmarkConfig, RemoteHostConfig
from lb_ui.tui.system.protocols import UI


def run_config_wizard(ui: UI, cfg: BenchmarkConfig) -> None:
    """Prompt the user for basic configuration settings."""
    ui.present.info("Configure remote host")
    name = ui.form.ask("Host name", default="node1")
    address = ui.form.ask("Host address", default="192.168.1.10")
    user = ui.form.ask("SSH user", default="ubuntu")
    key_path = ui.form.ask("SSH private key path", default="~/.ssh/id_rsa")
    become = ui.form.confirm("Use sudo (become)?", default=True)
    
    cfg.remote_hosts = [
        RemoteHostConfig(
            name=name,
            address=address,
            user=user,
            become=become,
            vars={
                "ansible_ssh_private_key_file": key_path,
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
            },
        )
    ]
    cfg.remote_execution.enabled = True
