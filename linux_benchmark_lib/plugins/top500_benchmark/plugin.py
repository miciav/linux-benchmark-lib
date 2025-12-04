"""
Top500 benchmark workload plugin.

Runs the geerlingguy/top500-benchmark Ansible playbook to execute the
High Performance Linpack (HPL) benchmark.
"""

from __future__ import annotations

import getpass
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


@dataclass
class Top500Config:
    """Configuration for the Top500 benchmark plugin."""

    workspace_dir: Optional[Path] = None
    tags: str = "setup,benchmark"
    inventory_path: Optional[Path] = None
    config_path: Optional[Path] = None
    extra_ansible_args: List[str] = field(default_factory=list)
    ansible_verbosity: int = 1
    debug: bool = False
    expected_runtime_seconds: int = 3600
    mpi_launcher: str = "fork"


class Top500Generator(BaseGenerator):
    """Workload generator that runs the Top500 benchmark via Ansible."""

    def __init__(self, config: Top500Config, name: str = "Top500BenchmarkGenerator"):
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen[str]] = None
        self.expected_runtime_seconds = max(0, int(config.expected_runtime_seconds))

        # Define workspace
        if self.config.workspace_dir:
            self.workspace = Path(self.config.workspace_dir).expanduser()
        else:
            self.workspace = Path.home() / ".lb" / "workspaces" / "top500_benchmark"
        
        # Check for pre-built HPL (e.g. in Docker)
        docker_hpl_root = Path("/opt/hpl")
        docker_xhpl = docker_hpl_root / "hpl-2.3" / "bin" / "Linux" / "xhpl"
        
        if docker_xhpl.exists():
            self.hpl_root = docker_hpl_root
            logger.info("Found pre-built HPL at %s", self.hpl_root)
        else:
            self.hpl_root = self.workspace / "build"

    def _validate_environment(self) -> bool:
        """
        Validate that required tools are present.
        """
        if not shutil.which("ansible-playbook"):
            logger.error("ansible-playbook not found")
            return False
        return True

    def _prepare_workspace(self) -> bool:
        """
        Ensure the workspace is populated with packaged assets.
        We copy to a writable workspace to avoid modifying the installed package
        and to allow dynamic configuration generation.
        """
        try:
            if not self.workspace.exists():
                self.workspace.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(PACKAGED_REPO_PATH, self.workspace)
                logger.info("Initialized workspace at %s", self.workspace)
            else:
                # Optionally update assets if needed, for now assume if exists it's good
                # or maybe check for a version file.
                pass
            return True
        except Exception as e:
            logger.error("Failed to prepare workspace at %s: %s", self.workspace, e)
            self._result = {"error": f"Workspace setup failed: {e}"}
            return False

    def _generate_inventory(self) -> Path:
        """Generate a localhost inventory if one is not provided."""
        if self.config.inventory_path:
            return Path(self.config.inventory_path).expanduser()
        
        inventory_path = self.workspace / "hosts.ini"
        if not inventory_path.exists():
            with open(inventory_path, "w") as f:
                f.write("[cluster]\nlocalhost ansible_connection=local\n")
        return inventory_path

    def _generate_config(self) -> Path:
        """Generate config.yml with overrides for local execution."""
        if self.config.config_path:
            return Path(self.config.config_path).expanduser()

        config_path = self.workspace / "config.yml"
        
        # We need to override hpl_root to be inside our workspace
        # and ssh info to match current user (or bypass ssh for local)
        # actually the playbook uses ssh keys even for localhost in some cases?
        # simpler to just point hpl_root to workspace/build
        
        # We append our overrides to the example config or just write a new one.
        # writing a new one is safer to ensure we control the variables.
        
        # Detect reasonable defaults for local run
        import multiprocessing
        cpu_count = multiprocessing.cpu_count()
        
        # Approximate Ns for quick run if not tuned
        # This is just a safe default; users should tune via config if they want max score
        
        content = f"""---
hpl_root: "{self.hpl_root}"
ssh_user: "{getpass.getuser()}"
ssh_user_home: "{Path.home()}"
mpi_launcher: "{self.config.mpi_launcher}"

ram_in_gb: 1
nodecount: 1

hpl_dat_opts:
  Ns: 5000
  NBs: 256
  Ps: 1
  Qs: {max(1, cpu_count // 2)}
"""
        if not config_path.exists():
            with open(config_path, "w") as f:
                f.write(content)
        
        return config_path

    def _is_setup_complete(self) -> bool:
        """Check if HPL is compiled and ready."""
        xhpl_path = self.hpl_root / "hpl-2.3" / "bin" / "Linux" / "xhpl"
        return xhpl_path.exists() and os.access(xhpl_path, os.X_OK)

    def _run_ansible(self, playbook: Path, inventory: Path, config: Path) -> int:
        """Execute ansible-playbook."""
        cmd = [
            "ansible-playbook",
            "-i", str(inventory),
            "-e", f"@{config}",
            "-e", f"assets_root={self.workspace}",
            str(playbook)
        ]
        if self.config.ansible_verbosity > 0:
            cmd.append("-" + "v" * self.config.ansible_verbosity)
        
        cmd.extend(self.config.extra_ansible_args)
        
        env = os.environ.copy()
        env["ANSIBLE_FORCE_COLOR"] = "0"
        
        logger.info("Running Ansible: %s", " ".join(cmd))
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.workspace,
            env=env
        )
        self._process = process
        
        stdout, stderr = process.communicate()
        
        # Log output (maybe truncated)
        if stdout:
            logger.debug("Ansible stdout (head): %s", stdout[:500])
        
        if process.returncode != 0:
            logger.error("Ansible execution failed with rc=%s", process.returncode)
            if stdout:
                logger.error("Ansible stdout (tail): %s", stdout[-2000:])
            if stderr:
                logger.error("Ansible stderr: %s", stderr)
            
            self._result = {
                "error": "Ansible execution failed",
                "returncode": process.returncode,
                "stdout": stdout,
                "stderr": stderr
            }
        else:
            # Try to parse Gflops from stdout if this was a run
            metrics = self._extract_hpl_metrics(stdout)
            self._result = {
                "returncode": 0,
                "stdout": stdout,
                "stderr": stderr,
                **metrics
            }
            
        return process.returncode

    def _extract_hpl_metrics(self, output: str) -> dict[str, Any]:
        """Extract numeric metrics from HPL output."""
        metrics: dict[str, Any] = {}
        matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*Gflops", output, flags=re.IGNORECASE)
        if matches:
            try:
                metrics["gflops"] = float(matches[-1])
            except ValueError:
                pass

        lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
        for line in reversed(lines):
            if "Gflops" in line or "Gflop/s" in line or "Gflop" in line:
                metrics["result_line"] = line
                break
        return metrics

    def _run_command(self) -> None:
        if not self._prepare_workspace():
            return

        inventory = self._generate_inventory()
        config = self._generate_config()
        
        setup_playbook = Path(__file__).parent / "ansible" / "setup.yml"
        run_playbook = Path(__file__).parent / "ansible" / "run.yml"

        if not self._is_setup_complete():
            logger.info("Setup required (xhpl not found). Running setup.yml...")
            rc = self._run_ansible(setup_playbook, inventory, config)
            if rc != 0:
                logger.error("Setup failed.")
                return
        else:
            logger.info("Setup already complete (xhpl found). Skipping setup.")

        logger.info("Running benchmark...")
        self._run_ansible(run_playbook, inventory, config)

    def _stop_workload(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()


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
            return Top500Config(ansible_verbosity=0)
        if level == WorkloadIntensity.MEDIUM:
            return Top500Config(ansible_verbosity=1)
        if level == WorkloadIntensity.HIGH:
            return Top500Config(ansible_verbosity=2)
        return None

    def get_required_apt_packages(self) -> List[str]:
        return ["ansible", "git", "openssh-client", "procps"]

    def get_required_local_tools(self) -> List[str]:
        return ["ansible-playbook", "git"]

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

    def get_ansible_setup_path(self) -> Optional[Path]:
        return Path(__file__).parent / "ansible" / "setup.yml"

    def get_ansible_teardown_path(self) -> Optional[Path]:
        return None


PLUGIN = Top500Plugin()
