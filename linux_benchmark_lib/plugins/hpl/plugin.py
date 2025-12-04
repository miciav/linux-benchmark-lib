"""
HPL (High Performance Linpack) workload plugin.
"""

import logging
import multiprocessing
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Type

from ...plugin_system.base_generator import BaseGenerator
from ...plugin_system.interface import WorkloadIntensity, WorkloadPlugin

logger = logging.getLogger(__name__)

HPL_VERSION = "2.3"


@dataclass
class HPLConfig:
    """Configuration for HPL benchmark."""

    # HPL.dat parameters
    n: int = 10000  # Problem size (N)
    nb: int = 256  # Block size (NB)
    p: int = 1  # Process grid rows
    q: int = 1  # Process grid cols

    # Execution parameters
    mpi_ranks: int = 1
    mpi_launcher: str = "fork"  # 'fork' for local, 'ssh' for distributed

    # Paths (optional override)
    workspace_dir: Optional[str] = None
    debug: bool = False
    expected_runtime_seconds: int = 3600


class HPLGenerator(BaseGenerator):
    """Generates and runs HPL workload."""

    def __init__(self, config: HPLConfig, name: str = "HPLGenerator") -> None:
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen[str]] = None
        self.expected_runtime_seconds = max(0, int(config.expected_runtime_seconds))

        # Determine workspace
        if self.config.workspace_dir:
            self.workspace = Path(self.config.workspace_dir).expanduser()
        else:
            self.workspace = Path.home() / ".lb" / "workspaces" / "hpl"

        # HPL binary location in workspace
        self.xhpl_path = (
            self.workspace / f"hpl-{HPL_VERSION}" / "bin" / "Linux" / "xhpl"
        )
        self.system_xhpl_path = Path("/opt") / f"hpl-{HPL_VERSION}" / "bin" / "Linux" / "xhpl"
        self.working_dir = self.xhpl_path.parent
        self.setup_playbook = Path(__file__).parent / "ansible" / "setup.yml"
        self._prepared = False

    def _validate_environment(self) -> bool:
        """Check if required tools exist and workspace is usable."""
        required_tools = ["mpirun"]
        # Only require ansible if we expect to build from source
        if not (self.xhpl_path.exists() or self.system_xhpl_path.exists()):
            required_tools.append("ansible-playbook")

        for tool in required_tools:
            if not shutil.which(tool):
                logger.error("%s not found in PATH", tool)
                return False

        try:
            self.workspace.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Cannot prepare workspace %s: %s", self.workspace, exc)
            return False

        if not self.setup_playbook.exists():
            logger.error("Setup playbook not found at %s", self.setup_playbook)
            return False

        return True

    def _run_ansible_setup(self) -> bool:
        """Run the setup playbook to install HPL from the packaged .deb."""
        logger.info("Installing HPL via Ansible...")
        cmd = [
            "ansible-playbook",
            str(self.setup_playbook),
            "-i",
            "localhost,",
            "-c",
            "local",
            "-e",
            f"hpl_workspace={self.workspace}",
            "-e",
            f"hpl_version={HPL_VERSION}",
        ]

        # Allow overriding workdir/deb source via environment for local runs
        lb_workdir = os.environ.get("LB_WORKDIR")
        if lb_workdir:
            cmd.extend(["-e", f"lb_workdir={lb_workdir}"])
        hpl_deb_src = os.environ.get("HPL_DEB_SRC")
        if hpl_deb_src:
            cmd.extend(["-e", f"hpl_deb_src={hpl_deb_src}"])
        cmd.append("-v")

        try:
            subprocess.run(cmd, check=True, env=os.environ.copy())
            return True
        except subprocess.CalledProcessError as exc:
            logger.error("HPL build failed: %s", exc)
            return False

    def _ensure_binary(self) -> bool:
        """
        Ensure xhpl exists, building it if necessary.
        """
        # Prefer workspace binary
        if self.xhpl_path.exists() and os.access(self.xhpl_path, os.X_OK):
            return True
        # Fallback to system-installed xhpl (e.g., from prebuilt image/deb)
        if self.system_xhpl_path.exists() and os.access(self.system_xhpl_path, os.X_OK):
            self.xhpl_path = self.system_xhpl_path
            self.working_dir = self.xhpl_path.parent
            return True

        # If neither binary exists, attempt build only when Ansible is available
        if not shutil.which("ansible-playbook"):
            self._result = {"error": "xhpl missing and ansible-playbook not available for build"}
            logger.error("xhpl missing and ansible-playbook not available for build")
            return False

        if not self._run_ansible_setup():
            self._result = {"error": "HPL setup failed"}
            return False

        if not (self.xhpl_path.exists() and os.access(self.xhpl_path, os.X_OK)):
            self._result = {"error": "xhpl missing or not executable after setup"}
            logger.error("xhpl not found at %s after setup", self.xhpl_path)
            return False

        return True

    def prepare(self) -> None:
        """
        Build HPL ahead of the run so collectors don't capture setup time.
        """
        if self._prepared:
            return

        if not self._ensure_binary():
            raise RuntimeError("Failed to prepare HPL binary")

        self._prepared = True

    def _generate_hpl_dat(self) -> None:
        """Generate the HPL.dat file in the working directory."""
        content = f"""HPLinpack benchmark input file
Innovative Computing Laboratory, University of Tennessee
HPL.out      output file name (if any)
6            device out (6=stdout,7=stderr,file)
1            # of problems sizes (N)
{self.config.n}        Ns
1            # of NBs
{self.config.nb}          NBs
0            PMAP process mapping (0=Row-,1=Column-major)
1            # of process grids (P x Q)
{self.config.p}            Ps
{self.config.q}            Qs
16.0         threshold
1            # of panel fact
2            PFACTs (0=left, 1=Crout, 2=Right)
1            # of recursive stopping criterium
4            NBMINs (>= 1)
1            # of panels in recursion
2            NDIVs
1            # of recursive panel fact.
1            RFACTs (0=left, 1=Crout, 2=Right)
1            # of broadcast
1            BCASTs (0=1rg,1=1rM,2=2rg,3=2rM,4=Lng,5=LnM)
1            # of lookahead depth
1            DEPTHs (>=0)
2            SWAP (0=bin-exch,1=long,2=mix)
64           swapping threshold
0            L1 in (0=transposed,1=no-transposed) form
0            U  in (0=transposed,1=no-transposed) form
1            Equilibration (0=no,1=yes)
8            memory alignment in double (> 0)
"""
        self.working_dir.mkdir(parents=True, exist_ok=True)
        dat_file = self.working_dir / "HPL.dat"
        with open(dat_file, "w") as file:
            file.write(content)
        logger.info("Generated HPL.dat at %s", dat_file)

    def _launcher_flags(self) -> list[str]:
        """
        Translate mpi_launcher config into mpirun flags.

        "fork" maps to an isolated launcher to avoid ssh requirements,
        any other non-empty value is passed to plm_rsh_agent.
        """
        launcher = (self.config.mpi_launcher or "").strip()
        if not launcher:
            return []
        if launcher == "fork":
            return ["--mca", "plm", "isolated"]
        return ["--mca", "plm_rsh_agent", launcher]

    def _run_command(self) -> None:
        """Execute the benchmark."""
        try:
            if not self._ensure_binary():
                return

            process_grid = max(1, self.config.p * self.config.q)
            mpi_ranks = max(1, self.config.mpi_ranks)
            if mpi_ranks != process_grid:
                logger.warning(
                    "Adjusting mpi_ranks from %s to match process grid P*Q=%s",
                    mpi_ranks,
                    process_grid,
                )
                mpi_ranks = process_grid

            self._generate_hpl_dat()

            cmd = [
                "mpirun",
                "--allow-run-as-root",
                "-np",
                str(mpi_ranks),
                *self._launcher_flags(),
                "./xhpl",
            ]

            logger.info("Running: %s", " ".join(cmd))

            self._process = subprocess.Popen(
                cmd,
                cwd=self.working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=os.environ.copy(),
            )

            stdout, stderr = self._process.communicate()
            result_metrics = self._parse_output(stdout or "")

            self._result = {
                "returncode": self._process.returncode,
                "stdout": stdout or "",
                "stderr": stderr or "",
                "command": " ".join(cmd),
                **result_metrics,
            }

            if self._process.returncode != 0:
                logger.error("HPL failed with rc=%s", self._process.returncode)
                if stderr:
                    logger.error("stderr: %s", stderr)

        except Exception as exc:
            logger.error("Execution error: %s", exc)
            self._result = {"error": str(exc)}
        finally:
            self._process = None
            self._is_running = False

    def _parse_output(self, output: str) -> dict[str, Any]:
        """Parse Gflops from HPL output."""
        metrics: dict[str, Any] = {}
        wr_pattern = re.compile(
            r"^W[A-Z0-9]+\s+\d+\s+\d+\s+\d+\s+\d+\s+[\d\.Ee\+\-]+\s+([\d\.Ee\+\-]+)"
        )

        for line in output.splitlines():
            line = line.strip()
            match = wr_pattern.match(line)
            if match:
                metrics["result_line"] = line
                try:
                    metrics["gflops"] = float(match.group(1))
                except ValueError:
                    pass

        if "gflops" not in metrics:
            fallbacks = re.findall(
                r"([0-9]+(?:\.[0-9]+)?)\s*Gflops", output, flags=re.IGNORECASE
            )
            if fallbacks:
                try:
                    metrics["gflops"] = float(fallbacks[-1])
                except ValueError:
                    pass

        return metrics

    def _stop_workload(self) -> None:
        proc = self._process
        if proc and proc.poll() is None:
            logger.info("Terminating HPL workload")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing HPL workload")
                proc.kill()
                proc.wait()
        self._process = None


class HPLPlugin(WorkloadPlugin):
    """HPL Plugin definition."""

    @property
    def name(self) -> str:
        return "hpl"

    @property
    def description(self) -> str:
        return "HPL (High Performance Linpack) 2.3 via OpenMPI"

    @property
    def config_cls(self) -> Type[HPLConfig]:
        return HPLConfig

    def create_generator(self, config: HPLConfig) -> HPLGenerator:
        return HPLGenerator(config)

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[HPLConfig]:
        cpu_count = multiprocessing.cpu_count()

        if level == WorkloadIntensity.LOW:
            return HPLConfig(n=5000, nb=128, p=1, q=1, mpi_ranks=1)
        elif level == WorkloadIntensity.MEDIUM:
            # Use half CPUs
            ranks = max(1, cpu_count // 2)
            return HPLConfig(n=10000, nb=256, p=1, q=ranks, mpi_ranks=ranks)
        elif level == WorkloadIntensity.HIGH:
            # Use all CPUs
            ranks = cpu_count
            return HPLConfig(n=20000, nb=256, p=1, q=ranks, mpi_ranks=ranks)
        return None

    def get_required_apt_packages(self) -> List[str]:
        return [
            "ansible",
            "build-essential",
            "gfortran",
            "openmpi-bin",
            "libopenmpi-dev",
            "libopenblas-dev",
            "make",
            "wget",
            "tar",
        ]

    def get_required_local_tools(self) -> List[str]:
        return ["mpirun", "make"]

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

    def get_ansible_setup_path(self) -> Optional[Path]:
        return Path(__file__).parent / "ansible" / "setup.yml"


PLUGIN = HPLPlugin()
