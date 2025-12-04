"""
Service for managing Multipass virtual machines lifecycle for benchmark execution.
Implements robust provisioning, SSH key injection, and automatic teardown via Context Manager pattern.
"""

import json
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Generator, Optional
from contextlib import contextmanager

from ..benchmark_config import RemoteHostConfig

logger = logging.getLogger(__name__)


class MultipassError(Exception):
    """Base exception for Multipass operations."""
    pass


class MultipassService:
    """
    Manages the lifecycle of a Multipass VM for benchmarking.
    
    Design Principles:
    - Infrastructure as Code (Ephemeral): VMs are created for the task and destroyed after.
    - Security: Uses ephemeral SSH keys, avoiding dependency on system/root keys.
    - Robustness: Retries operations that depend on network/boot timing.
    """

    def __init__(self, temp_dir: Path):
        """
        Initialize the service.
        
        Args:
            temp_dir: Directory to store ephemeral SSH keys.
        """
        self.temp_dir = temp_dir
        # Use a unique ID to avoid collisions with existing user VMs
        self.vm_name = f"lb-worker-{uuid.uuid4().hex[:8]}"
        self.ssh_key_path = self.temp_dir / f"{self.vm_name}_id_rsa"
        self.ssh_pub_path = self.temp_dir / f"{self.vm_name}_id_rsa.pub"
        self._ensure_multipass_available()

    def _ensure_multipass_available(self) -> None:
        """Verifies that the multipass CLI tool is installed."""
        if shutil.which("multipass") is None:
            raise MultipassError(
                "Multipass CLI tool not found in PATH. Please install it (e.g., 'brew install --cask multipass')."
            )

    def _generate_ephemeral_keys(self) -> None:
        """
        Generates a fresh SSH key pair for this specific benchmark run.
        This avoids permission issues with reading system-level Multipass keys.
        """
        logger.info(f"Generating ephemeral SSH keys at {self.ssh_key_path}")
        try:
            # Generate RSA key, 4096 bits, no passphrase
            subprocess.run(
                ["ssh-keygen", "-t", "rsa", "-b", "4096", "-f", str(self.ssh_key_path), "-N", ""],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            # Secure the private key (chmod 600)
            self.ssh_key_path.chmod(0o600)
        except subprocess.CalledProcessError as e:
            raise MultipassError(f"Failed to generate SSH keys: {e.stderr.decode()}")

    def _launch_vm(self, image: str = "24.04") -> None:
        """
        Launches the VM instance via Multipass.
        
        Args:
            image: The Ubuntu image alias to use.
        """
        logger.info(f"Launching Multipass VM '{self.vm_name}' (image: {image})...")
        # We use conservative defaults: 2 CPUs, 4GB RAM to ensure it runs on most dev machines.
        # Ideally, these should be configurable via CLI args in the future.
        cmd = [
            "multipass", "launch", image,
            "--name", self.vm_name,
            "--cpus", "2",
            "--disk", "10G",
            "--memory", "4G"
        ]
        
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            logger.warning(f"Image '{image}' failed to launch. Attempting fallback to 'lts'...")
            try:
                cmd[2] = "lts"
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as e:
                raise MultipassError(f"Failed to launch VM: {e}")

    def _get_ip_address(self) -> str:
        """
        Retrieves the IPv4 address of the VM.
        Uses exponential-like polling because IP assignment via DHCP inside the VM isn't instantaneous.
        """
        logger.debug(f"Waiting for IP address of {self.vm_name}...")
        attempts = 15
        for i in range(attempts):
            try:
                result = subprocess.run(
                    ["multipass", "info", self.vm_name, "--format", "json"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                info = json.loads(result.stdout)
                # Navigate the JSON structure: info -> <vm_name> -> ipv4 -> [0]
                ipv4_list = info.get("info", {}).get(self.vm_name, {}).get("ipv4", [])
                if ipv4_list:
                    return ipv4_list[0]
            except (json.JSONDecodeError, KeyError, IndexError, subprocess.CalledProcessError):
                pass
            
            time.sleep(2)
        
        raise MultipassError(f"Timed out waiting for IP address assignment for {self.vm_name}")

    def _inject_ssh_key(self) -> None:
        """
        Injects the generated public key into the VM's authorized_keys.
        This bridges the gap between Multipass internal auth and Ansible's standard SSH requirement.
        """
        logger.info("Injecting ephemeral SSH public key...")
        if not self.ssh_pub_path.exists():
            raise MultipassError("Public key file not found.")
            
        pub_key_content = self.ssh_pub_path.read_text().strip()
        
        # Create .ssh dir and append key safely
        # We use 'multipass exec' which uses the internal/socket socket to run commands.
        bash_script = (
            "mkdir -p ~/.ssh && "
            f"echo '{pub_key_content}' >> ~/.ssh/authorized_keys && "
            "chmod 600 ~/.ssh/authorized_keys && "
            "chmod 700 ~/.ssh"
        )
        
        try:
            subprocess.run(
                ["multipass", "exec", self.vm_name, "--", "bash", "-c", bash_script],
                check=True,
                stderr=subprocess.PIPE
            )
        except subprocess.CalledProcessError as e:
            raise MultipassError(f"Failed to inject SSH key: {e.stderr.decode()}")

    def teardown(self) -> None:
        """
        Destroys the VM and removes local key files.
        This method is designed to be exception-safe (best effort).
        """
        logger.info(f"Tearing down Multipass VM '{self.vm_name}'...")
        
        # 1. Destroy VM
        if shutil.which("multipass"):
            try:
                subprocess.run(
                    ["multipass", "delete", self.vm_name, "--purge"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                logger.warning(f"Error during VM deletion: {e}")
        
        # 2. Remove local keys
        try:
            if self.ssh_key_path.exists():
                self.ssh_key_path.unlink()
            if self.ssh_pub_path.exists():
                self.ssh_pub_path.unlink()
        except Exception as e:
            logger.warning(f"Error cleaning up local SSH keys: {e}")

    @contextmanager
    def provision(self) -> Generator[RemoteHostConfig, None, None]:
        """
        Context Manager to provision resources and ensure cleanup.
        
        Yields:
            RemoteHostConfig: Configuration object ready for Ansible.
        """
        self._generate_ephemeral_keys()
        try:
            self._launch_vm()
            ip = self._get_ip_address()
            self._inject_ssh_key()
            
            logger.info(f"Multipass VM Provisioned: {self.vm_name} @ {ip}")
            
            # Construct the configuration for Ansible
            host_config = RemoteHostConfig(
                name=self.vm_name,
                address=ip,
                user="ubuntu", # Default Multipass user
                become=True,   # We need sudo for benchmark installation
                vars={
                    "ansible_ssh_private_key_file": str(self.ssh_key_path.absolute()),
                    # Vital for ephemeral VMs: do not check host keys (fingerprint will change every run)
                    "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
                    "ansible_python_interpreter": "/usr/bin/python3"
                }
            )
            yield host_config
            
        except Exception as e:
            logger.error(f"Multipass provisioning failed: {e}")
            raise
        finally:
            self.teardown()
