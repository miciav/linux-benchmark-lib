"""
HPL (High Performance Linpack) workload plugin.
"""

import logging
import math
import multiprocessing
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Optional

from pydantic import Field, model_validator

from ...base_generator import CommandGenerator
from ...interface import SimpleWorkloadPlugin, WorkloadIntensity, BasePluginConfig

logger = logging.getLogger(__name__)

HPL_VERSION = "2.3"


class HPLConfig(BasePluginConfig):
    """Configuration for HPL benchmark."""

    # HPL.dat parameters
    n: int = Field(default=10000, gt=0, description="Problem size (N)")
    nb: int = Field(default=256, gt=0, description="Block size (NB)")
    p: int = Field(default=1, gt=0, description="Process grid rows")
    q: int = Field(default=1, gt=0, description="Process grid cols")

    # Execution parameters
    mpi_ranks: int = Field(default=1, gt=0, description="Number of MPI ranks")
    mpi_launcher: str = Field(default="fork", description="'fork' for local, 'ssh' for distributed MPI")

    # Paths (optional override)
    workspace_dir: Optional[str] = Field(default=None, description="Custom workspace directory for HPL files")
    debug: bool = Field(default=False, description="Enable debug logging")
    expected_runtime_seconds: int = Field(default=3600, gt=0, description="Expected runtime of HPL in seconds (used for timeout hints)")

    @model_validator(mode="after")
    def validate_mpi_ranks(self) -> "HPLConfig":
        if self.mpi_ranks != (self.p * self.q):
            logger.warning(
                "HPLConfig: mpi_ranks (%d) does not match process grid p*q (%d*%d=%d). "
                "Ensure this is intentional. Adjusting mpi_ranks to match p*q for consistency if not set by user.",
                self.mpi_ranks, self.p, self.q, self.p * self.q
            )
        return self


class HPLGenerator(CommandGenerator):
    """Generates and runs HPL workload."""

    def __init__(self, config: HPLConfig, name: str = "HPLGenerator") -> None:
        super().__init__(name, config)
        # self.expected_runtime_seconds now comes directly from config.expected_runtime_seconds
        # No need for env var parsing here.

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
        self._prepared = False

    def _validate_environment(self) -> bool:
        """Check if required tools exist and workspace is usable."""
        for tool in ("mpirun",):
            if not shutil.which(tool):
                logger.error("%s not found in PATH", tool)
                return False

        try:
            self.workspace.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Cannot prepare workspace %s: %s", self.workspace, exc)
            return False

        return True

    def _ensure_binary(self) -> bool:
        """
        Ensure xhpl exists; remote setup must install the deb.
        """
        # Prefer workspace binary
        if self.xhpl_path.exists() and os.access(self.xhpl_path, os.X_OK):
            return True
        # Fallback to system-installed xhpl (e.g., from prebuilt image/deb)
        if self.system_xhpl_path.exists() and os.access(self.system_xhpl_path, os.X_OK):
            self.xhpl_path = self.system_xhpl_path
            self.working_dir = self.xhpl_path.parent
            return True

        # If neither binary exists, fail fast: remote/multipass setup must install the deb.
        self._result = {"error": "xhpl missing; ensure remote setup installed the HPL .deb"}
        logger.error("xhpl missing; ensure remote setup installed the HPL .deb")
        return False

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

    def _build_command(self) -> list[str]:
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

        return [
            "mpirun",
            "--allow-run-as-root",
            "-np",
            str(mpi_ranks),
            *self._launcher_flags(),
            "./xhpl",
        ]

    def _popen_kwargs(self) -> dict[str, Any]:
        return {
            "cwd": self.working_dir,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "env": os.environ.copy(),
        }

    def _timeout_seconds(self) -> Optional[int]:
        return self.config.expected_runtime_seconds + self.config.timeout_buffer

    def _build_result(
        self,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> dict[str, Any]:
        result_metrics = self._parse_output(stdout or "")
        result = super()._build_result(cmd, stdout, stderr, returncode)
        result.update(result_metrics)
        return result

    def _after_run(
        self,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> None:
        # Surface common failure modes even when HPL exits 0
        if stdout:
            if "Memory allocation failed" in stdout:
                msg = (
                    "HPL reported memory allocation failure; adjust N/P/Q or provide more RAM. "
                    f"N={self.config.n}, P={self.config.p}, Q={self.config.q}"
                )
                self._result["error"] = msg
                logger.error(msg)
            else:
                skipped = re.search(
                    r"([0-9]+)\s+tests skipped", stdout, flags=re.IGNORECASE
                )
                if skipped:
                    try:
                        if int(skipped.group(1)) > 0:
                            msg = (
                                "HPL skipped tests due to illegal input; adjust N/P/Q or install deps."
                            )
                            self._result["error"] = msg
                            logger.error(msg)
                    except Exception:
                        pass

            if "HPL ERROR" in stdout and "error" not in self._result:
                self._result["error"] = "HPL reported an internal error"

        if returncode not in (None, 0) and "error" not in self._result:
            self._result["error"] = f"HPL exited with return code {returncode}"

    def _log_failure(
        self, returncode: int, stdout: str, stderr: str, cmd: list[str]
    ) -> None:
        logger.error("HPL failed with rc=%s", returncode)
        if stderr:
            logger.error("stderr: %s", stderr)

    def _run_command(self) -> None:
        if not self._ensure_binary():
            self._is_running = False
            return
        super()._run_command()

    def _parse_output(self, output: str) -> dict[str, Any]:
        """Parse summary metrics from HPL stdout."""
        metrics: dict[str, Any] = {}

        # Typical summary line:
        # WR00C2R4        N    NB     P     Q        Time       Gflops
        wr_pattern = re.compile(
            r"^(W[A-Z0-9]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d\.Ee\+\-]+)\s+([\d\.Ee\+\-]+)"
        )
        residual_pattern = re.compile(
            r"\|\|Ax-b\|\|.*=\s*([\d\.Ee\+\-]+)", flags=re.IGNORECASE
        )

        last_wr: tuple[str, int, int, int, int, float, float] | None = None

        for raw in output.splitlines():
            line = raw.strip()
            if not line:
                continue
            match = wr_pattern.match(line)
            if match:
                try:
                    last_wr = (
                        match.group(1),
                        int(match.group(2)),
                        int(match.group(3)),
                        int(match.group(4)),
                        int(match.group(5)),
                        float(match.group(6)),
                        float(match.group(7)),
                    )
                except Exception:
                    continue
                continue

            res_match = residual_pattern.search(line)
            if res_match and "residual" not in metrics:
                try:
                    metrics["residual"] = float(res_match.group(1))
                except ValueError:
                    pass
                continue

            if line.upper().startswith(("PASSED", "FAILED")):
                metrics["residual_passed"] = line.upper().startswith("PASSED")

        if last_wr:
            tag, n, nb, p, q, time_s, gflops = last_wr
            metrics.update(
                {
                    "result_line": tag,
                    "n": n,
                    "nb": nb,
                    "p": p,
                    "q": q,
                    "time_seconds": time_s,
                    "gflops": gflops,
                }
            )

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


class HPLPlugin(SimpleWorkloadPlugin):
    """HPL Plugin definition."""

    NAME = "hpl"
    DESCRIPTION = "HPL (High Performance Linpack) 2.3 via OpenMPI"
    CONFIG_CLS = HPLConfig
    GENERATOR_CLS = HPLGenerator
    REQUIRED_APT_PACKAGES = [
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
    REQUIRED_LOCAL_TOOLS = ["mpirun", "make"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[HPLConfig]:
        cpu_count = multiprocessing.cpu_count()

        def _grid_for_ranks(ranks: int) -> tuple[int, int]:
            """Choose a near-square process grid for better load balance."""
            if ranks <= 1:
                return (1, 1)
            q = math.isqrt(ranks)
            while ranks % q != 0 and q > 1:
                q -= 1
            p = ranks // q
            return (p, q)

        if level == WorkloadIntensity.LOW:
            return HPLConfig(n=5000, nb=128, p=1, q=1, mpi_ranks=1)
        elif level == WorkloadIntensity.MEDIUM:
            # Use half CPUs
            ranks = max(1, cpu_count // 2)
            p, q = _grid_for_ranks(ranks)
            return HPLConfig(n=20000, nb=256, p=p, q=q, mpi_ranks=ranks)
        elif level == WorkloadIntensity.HIGH:
            # Use all CPUs
            ranks = cpu_count
            # Increase problem size and block to drive multi-minute runs on typical hosts
            p, q = _grid_for_ranks(ranks)
            return HPLConfig(n=45000, nb=384, p=p, q=q, mpi_ranks=ranks)
        return None

    def export_results_to_csv(
        self,
        results: List[dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> List[Path]:
        """Export HPL summary metrics (per repetition) to a CSV file."""
        import pandas as pd

        rows: list[dict[str, Any]] = []
        for entry in results:
            rep = entry.get("repetition")
            gen_result = entry.get("generator_result") or {}
            rows.append(
                {
                    "run_id": run_id,
                    "workload": test_name,
                    "repetition": rep,
                    "returncode": gen_result.get("returncode"),
                    "success": entry.get("success"),
                    "duration_seconds": entry.get("duration_seconds"),
                    "n": gen_result.get("n"),
                    "nb": gen_result.get("nb"),
                    "p": gen_result.get("p"),
                    "q": gen_result.get("q"),
                    "time_seconds": gen_result.get("time_seconds"),
                    "gflops": gen_result.get("gflops"),
                    "residual": gen_result.get("residual"),
                    "residual_passed": gen_result.get("residual_passed"),
                    "result_line": gen_result.get("result_line"),
                    "max_retries": gen_result.get("max_retries"), # Add inherited field
                    "tags": gen_result.get("tags"), # Add inherited field
                }
            )

        if not rows:
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{test_name}_plugin.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        return [csv_path]


PLUGIN = HPLPlugin()
