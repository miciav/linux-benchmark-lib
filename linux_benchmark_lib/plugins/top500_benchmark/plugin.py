"""
Top500 benchmark workload plugin.

Runs the geerlingguy/top500-benchmark Ansible playbook to execute the
High Performance Linpack (HPL) benchmark. The plugin focuses on the single-node
flow by default (setup + benchmark tags) but allows full control over tags and
Ansible arguments when needed.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple, Type

from ...plugin_system.base_generator import BaseGenerator
from ...plugin_system.interface import WorkloadIntensity, WorkloadPlugin

logger = logging.getLogger(__name__)
PACKAGED_REPO_PATH = Path(__file__).parent / "assets" / "top500-benchmark"


def _default_repo_path() -> Path:
    """
    Return the default repo path.

    We prefer the packaged playbook shipped with the plugin to avoid repeated clones.
    """
    return PACKAGED_REPO_PATH


@dataclass
class Top500Config:
    """Configuration for the Top500 benchmark plugin."""

    repo_url: str = "https://github.com/geerlingguy/top500-benchmark.git"
    branch: str = "master"
    workdir: Path = field(default_factory=_default_repo_path)
    tags: str = "setup,benchmark"
    inventory_path: Optional[Path] = None
    config_path: Optional[Path] = None
    extra_ansible_args: List[str] = field(default_factory=list)
    refresh_repo: bool = False
    ansible_verbosity: int = 4
    debug: bool = False
    expected_runtime_seconds: int = 3600


class Top500Generator(BaseGenerator):
    """Workload generator that runs the Top500 benchmark via Ansible."""

    def __init__(self, config: Top500Config, name: str = "Top500BenchmarkGenerator"):
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen[str]] = None
        # Hint to the runner about typical runtime (HPL build+run is long)
        self.expected_runtime_seconds = max(0, int(config.expected_runtime_seconds))

    def _command_exists(self, command: str) -> bool:
        """Check if a command is available in PATH."""
        try:
            result = subprocess.run(
                ["which", command],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                logger.error("%s command not found", command)
                return False
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error checking for %s: %s", command, exc)
            return False

    def _validate_environment(self) -> bool:
        """
        Validate that required tools are present.

        Ansible is always required. Git is required when the repository needs to
        be cloned or refreshed.
        """
        repo_path = Path(self.config.workdir).expanduser()
        packaged_available = PACKAGED_REPO_PATH.exists()
        needs_clone = not repo_path.exists() and not packaged_available
        git_needed = self.config.refresh_repo or needs_clone

        if not self._command_exists("ansible-playbook"):
            return False
        if git_needed and not self._command_exists("git"):
            return False
        return True

    def _clone_repository(self, repo_path: Path) -> bool:
        """Clone the benchmark repository into repo_path."""
        cmd = [
            "git",
            "clone",
            "--branch",
            self.config.branch,
            "--depth",
            "1",
            self.config.repo_url,
            str(repo_path),
        ]
        logger.info("Cloning Top500 benchmark repository: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True, capture_output=not self.config.debug)
            return True
        except subprocess.CalledProcessError as exc:
            stdout_raw: Any = exc.stdout
            stderr_raw: Any = exc.stderr
            stdout = (
                stdout_raw.decode() if isinstance(stdout_raw, (bytes, bytearray)) else stdout_raw
            ) or ""
            stderr = (
                stderr_raw.decode() if isinstance(stderr_raw, (bytes, bytearray)) else stderr_raw
            ) or ""
            logger.error("Failed to clone repository: %s", stderr or stdout)
            self._result = {"error": "git clone failed", "stdout": stdout, "stderr": stderr}
            return False

    def _update_repository(self, repo_path: Path) -> bool:
        """Pull the latest changes for the configured branch."""
        cmd = ["git", "-C", str(repo_path), "pull", "--ff-only", "origin", self.config.branch]
        logger.info("Updating Top500 benchmark repository: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True, capture_output=not self.config.debug)
            return True
        except subprocess.CalledProcessError as exc:
            stdout_raw: Any = exc.stdout
            stderr_raw: Any = exc.stderr
            stdout = (
                stdout_raw.decode() if isinstance(stdout_raw, (bytes, bytearray)) else stdout_raw
            ) or ""
            stderr = (
                stderr_raw.decode() if isinstance(stderr_raw, (bytes, bytearray)) else stderr_raw
            ) or ""
            logger.error("Failed to update repository: %s", stderr or stdout)
            self._result = {"error": "git pull failed", "stdout": stdout, "stderr": stderr}
            return False

    def _ensure_repository(self, repo_path: Path) -> bool:
        """Ensure the repository exists locally."""
        packaged_path = PACKAGED_REPO_PATH
        if repo_path.exists():
            if (repo_path / ".git").exists():
                if self.config.refresh_repo:
                    return self._update_repository(repo_path)
                return True
            if (repo_path / "main.yml").exists():
                return True
            if self.config.refresh_repo:
                logger.error("Cannot refresh repository without git metadata at %s", repo_path)
                self._result = {"error": f"Cannot refresh non-git repository at {repo_path}"}
                return False
            return True

        # If repo_path is different from the packaged assets, seed from packaged copy
        if repo_path != packaged_path and packaged_path.exists():
            try:
                shutil.copytree(packaged_path, repo_path)
                return True
            except Exception as exc:
                logger.error("Failed to copy packaged repository to %s: %s", repo_path, exc)
                self._result = {"error": f"Failed to copy packaged repository: {exc}"}
                return False

        repo_path.parent.mkdir(parents=True, exist_ok=True)
        return self._clone_repository(repo_path)

    def _copy_if_missing(self, source: Path, destination: Path) -> None:
        """Copy a file into place when the destination is missing."""
        if destination.exists():
            return
        if not source.exists():
            raise FileNotFoundError(f"Missing example file: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, destination)
        logger.debug("Copied %s to %s", source, destination)

    def _prepare_files(self, repo_path: Path) -> Tuple[Path, Path]:
        """
        Ensure inventory and config files exist and return their paths.

        If custom paths are supplied, they must already exist. Otherwise, the
        plugin copies the example files provided by the upstream project.
        """
        inventory_raw = self.config.inventory_path
        config_raw = self.config.config_path

        inventory_path = (
            Path(inventory_raw).expanduser() if inventory_raw else repo_path / "hosts.ini"
        )
        config_path = Path(config_raw).expanduser() if config_raw else repo_path / "config.yml"

        if not inventory_raw:
            example_inventory = repo_path / "example.hosts.ini"
            self._copy_if_missing(example_inventory, inventory_path)
        elif not inventory_path.exists():
            raise FileNotFoundError(f"Inventory file does not exist: {inventory_path}")

        if not config_raw:
            example_config = repo_path / "example.config.yml"
            self._copy_if_missing(example_config, config_path)
        elif not config_path.exists():
            raise FileNotFoundError(f"Config file does not exist: {config_path}")

        return inventory_path, config_path

    def _build_ansible_command(self, inventory: Path, config: Path) -> List[str]:
        """Build the ansible-playbook command."""
        cmd: List[str] = ["ansible-playbook", "main.yml", "-i", str(inventory)]
        if self.config.tags:
            cmd.extend(["--tags", self.config.tags])
        cmd.extend(["-e", f"@{config}"])
        if self.config.ansible_verbosity > 0:
            verbosity_flag = "v" * min(self.config.ansible_verbosity, 4)
            cmd.append(f"-{verbosity_flag}")
        cmd.extend(self.config.extra_ansible_args)
        return cmd

    def _extract_gflops(self, output: str) -> Optional[float]:
        """Attempt to parse the last reported Gflops value from HPL output."""
        matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*Gflops", output, flags=re.IGNORECASE)
        if not matches:
            return None
        try:
            return float(matches[-1])
        except ValueError:
            return None

    def _extract_hpl_metrics(self, output: str) -> dict[str, Any]:
        """
        Extract numeric metrics from HPL output.

        Returns:
            Dict with gflops (if found) and last result line for troubleshooting.
        """
        metrics: dict[str, Any] = {}
        gflops = self._extract_gflops(output)
        if gflops is not None:
            metrics["gflops"] = gflops

        # Capture the last non-empty line that looks like the HPL result line
        lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
        for line in reversed(lines):
            if "Gflops" in line or "Gflop/s" in line or "Gflop" in line:
                metrics.setdefault("result_line", line)
                break
        if "result_line" not in metrics and lines:
            metrics["result_line"] = lines[-1]
        return metrics

    def _run_command(self) -> None:
        repo_path = Path(self.config.workdir).expanduser()
        try:
            if not self._ensure_repository(repo_path):
                return

            inventory_path, config_path = self._prepare_files(repo_path)
            cmd = self._build_ansible_command(inventory_path, config_path)
            logger.info("Running Top500 benchmark: %s", " ".join(cmd))

            env = {**os.environ, "ANSIBLE_FORCE_COLOR": "0"}
            self._process = subprocess.Popen(
                cmd,
                cwd=repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            stdout, stderr = self._process.communicate()

            combined_output = (stdout or "") + "\\n" + (stderr or "")
            metrics = self._extract_hpl_metrics(combined_output)

            self._result = {
                "stdout": stdout or "",
                "stderr": stderr or "",
                "returncode": self._process.returncode,
                "command": " ".join(cmd),
                **metrics,
            }

            if self._process.returncode != 0:
                logger.error("Top500 benchmark failed with return code %s", self._process.returncode)
        except Exception as exc:
            logger.error("Error running Top500 benchmark: %s", exc)
            self._result = {"error": str(exc)}
        finally:
            self._process = None
            self._is_running = False

    def _stop_workload(self) -> None:
        """Stop an in-flight ansible-playbook run."""
        proc = self._process
        if proc and proc.poll() is None:
            logger.info("Terminating Top500 benchmark process")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing Top500 benchmark process")
                proc.kill()
                proc.wait()


class Top500Plugin(WorkloadPlugin):
    """Plugin definition for the Top500 benchmark."""

    @property
    def name(self) -> str:
        return "top500_benchmark"

    @property
    def description(self) -> str:
        return "HPL Linpack via geerlingguy/top500-benchmark"

    @property
    def config_cls(self) -> Type[Top500Config]:
        return Top500Config

    def create_generator(self, config: Top500Config) -> Top500Generator:
        return Top500Generator(config)

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[Top500Config]:
        if level == WorkloadIntensity.LOW:
            return Top500Config(tags="setup,benchmark", ansible_verbosity=0)
        if level == WorkloadIntensity.MEDIUM:
            return Top500Config(tags="setup,ssh,benchmark", ansible_verbosity=1)
        if level == WorkloadIntensity.HIGH:
            return Top500Config(
                tags="setup,ssh,benchmark",
                ansible_verbosity=2,
                refresh_repo=True,
            )
        return None

    def get_required_apt_packages(self) -> List[str]:
        return ["ansible", "git", "openssh-client"]

    def get_required_local_tools(self) -> List[str]:
        return ["ansible-playbook", "git"]

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

    def get_ansible_setup_path(self) -> Optional[Path]:
        return None

    def get_ansible_teardown_path(self) -> Optional[Path]:
        return None


PLUGIN = Top500Plugin()
