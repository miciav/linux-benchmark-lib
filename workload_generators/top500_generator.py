"""
Top500 (HPL Linpack) workload generator using the upstream Ansible playbook.

This generator clones the geerlingguy/top500-benchmark repository onto the host,
renders a config/hosts inventory, and executes the playbook via ansible-playbook.
It is intended for single-node runs by default (localhost inventory), but users can
override the inventory hosts to target multiple nodes the playbook can reach.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import yaml

from benchmark_config import Top500Config
from ._base_generator import BaseGenerator


logger = logging.getLogger(__name__)


def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _deep_update(target: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge updates into target and return it.
    """
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key] = _deep_update(target.get(key, {}), value)
        else:
            target[key] = value
    return target


class Top500Generator(BaseGenerator):
    """Generator to run the Top500 HPL playbook via ansible-playbook."""

    def __init__(self, config: Top500Config, name: str = "Top500Generator"):
        super().__init__(name)
        self.config = config
        self._process: subprocess.Popen | None = None

    def _validate_environment(self) -> bool:
        if not _which("git"):
            logger.error("git not found in PATH")
            return False
        if not _which("ansible-playbook"):
            logger.error("ansible-playbook not found in PATH")
            return False
        return True

    def _ensure_repo(self, workdir: Path) -> None:
        if workdir.exists() and (workdir / ".git").exists():
            return
        workdir.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", "--depth", "1", self.config.repo_url, str(workdir)]
        logger.info("Cloning top500 playbook: %s", " ".join(cmd))
        subprocess.run(cmd, check=True)

    def _checkout_ref(self, workdir: Path) -> None:
        if not self.config.repo_ref:
            return
        cmd = ["git", "fetch", "--depth", "1", "origin", self.config.repo_ref]
        subprocess.run(cmd, cwd=workdir, check=True)
        subprocess.run(["git", "checkout", self.config.repo_ref], cwd=workdir, check=True)

    def _prepare_config(self, workdir: Path) -> None:
        config_path = workdir / "config.yml"
        if not config_path.exists():
            shutil.copyfile(workdir / "example.config.yml", config_path)

        if self.config.config_overrides:
            base = yaml.safe_load(config_path.read_text()) or {}
            merged = _deep_update(base, dict(self.config.config_overrides))
            config_path.write_text(yaml.safe_dump(merged, sort_keys=False))

    def _prepare_hosts(self, workdir: Path) -> Path:
        hosts_path = workdir / "hosts.ini"
        lines = ["[cluster]"]
        lines.extend(self.config.inventory_hosts)
        hosts_path.write_text("\n".join(lines) + "\n")
        return hosts_path

    def _run_command(self) -> None:
        workdir = self.config.workdir.expanduser().resolve()
        try:
            self._ensure_repo(workdir)
            self._checkout_ref(workdir)
            self._prepare_config(workdir)
            hosts_path = self._prepare_hosts(workdir)

            tags = ",".join(self.config.tags) if self.config.tags else "setup,benchmark"
            cmd: List[str] = ["ansible-playbook", "-i", str(hosts_path), "main.yml", "--tags", tags]
            logger.info("Running Top500 playbook: %s", " ".join(cmd))

            self._process = subprocess.Popen(
                cmd,
                cwd=str(workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = self._process.communicate()
            self._result = {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": self._process.returncode,
                "command": " ".join(cmd),
            }
            if self._process.returncode != 0:
                logger.error("Top500 playbook failed with return code %s", self._process.returncode)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Top500 generator failed: %s", exc)
            self._result = {"error": str(exc)}
        finally:
            self._process = None
            self._is_running = False

    def stop(self) -> None:
        """Terminate ansible-playbook if running."""
        if self._process and self._process.poll() is None:
            logger.info("Terminating Top500 playbook process")
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing Top500 playbook process")
                self._process.kill()
                self._process.wait()
        super().stop()
