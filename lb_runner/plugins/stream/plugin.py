"""
STREAM (memory bandwidth) workload plugin.

This plugin supports compile-time tuning of STREAM via:
  - STREAM_ARRAY_SIZE
  - NTIMES
by recompiling a variant binary into the workspace when needed.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Optional, Type

from pydantic import Field

from ...plugin_system.base_generator import BaseGenerator
from ...plugin_system.interface import BasePluginConfig, WorkloadIntensity, WorkloadPlugin

logger = logging.getLogger(__name__)

STREAM_VERSION = "5.10"
UPSTREAM_COMMIT = "6703f7504a38a8da96b353cadafa64d3c2d7a2d3"

DEFAULT_STREAM_ARRAY_SIZE = 10_000_000
DEFAULT_NTIMES = 10


class StreamConfig(BasePluginConfig):
    """Configuration for STREAM benchmark."""

    stream_array_size: int = Field(
        default=DEFAULT_STREAM_ARRAY_SIZE,
        gt=0,
        description="STREAM_ARRAY_SIZE (compile-time); number of elements per array",
    )
    ntimes: int = Field(
        default=DEFAULT_NTIMES,
        gt=1,
        description="NTIMES (compile-time); number of iterations per kernel",
    )
    recompile: bool = Field(
        default=False,
        description="Force recompiling the stream binary into the workspace before running",
    )

    threads: int = Field(
        default=0,
        ge=0,
        description="OMP_NUM_THREADS (0 means do not set; let OpenMP decide)",
    )
    use_numactl: bool = Field(
        default=False,
        description="Run under numactl for more stable bandwidth measurements",
    )
    numactl_args: List[str] = Field(
        default_factory=lambda: ["--interleave=all"],
        description="Arguments passed to numactl when use_numactl is enabled",
    )

    workspace_dir: Optional[str] = Field(
        default=None,
        description="Custom workspace directory for tuned binaries and temporary artifacts",
    )
    expected_runtime_seconds: int = Field(
        default=60,
        gt=0,
        description="Expected runtime used to derive a timeout hint",
    )


class StreamGenerator(BaseGenerator):
    """Generates and runs STREAM workload."""

    def __init__(self, config: StreamConfig, name: str = "StreamGenerator") -> None:
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen[str]] = None

        if self.config.workspace_dir:
            self.workspace = Path(self.config.workspace_dir).expanduser()
        else:
            self.workspace = Path.home() / ".lb" / "workspaces" / "stream"

        self.workspace_bin_dir = self.workspace / f"stream-{STREAM_VERSION}" / "bin"
        self.workspace_src_dir = self.workspace / f"stream-{STREAM_VERSION}" / "src"

        self.system_stream_path = (
            Path("/opt") / f"stream-{STREAM_VERSION}" / "bin" / "stream"
        )
        self.stream_path = self.workspace_bin_dir / "stream"
        self.working_dir = self.workspace_bin_dir

        self._prepared = False

    def _needs_recompile(self) -> bool:
        return bool(
            self.config.recompile
            or self.config.stream_array_size != DEFAULT_STREAM_ARRAY_SIZE
            or self.config.ntimes != DEFAULT_NTIMES
        )

    def _validate_environment(self) -> bool:
        if self._needs_recompile():
            if not shutil.which("gcc"):
                logger.error("gcc not found in PATH (needed to compile tuned STREAM)")
                return False

        if self.config.use_numactl and not shutil.which("numactl"):
            logger.error("numactl not found in PATH")
            return False

        try:
            self.workspace_bin_dir.mkdir(parents=True, exist_ok=True)
            self.workspace_src_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Cannot prepare workspace %s: %s", self.workspace, exc)
            return False

        return True

    def _upstream_stream_c(self) -> Path:
        upstream = Path(__file__).resolve().parent / "upstream" / "stream.c"
        if not upstream.exists():
            raise FileNotFoundError(f"Missing vendored stream.c at {upstream}")
        return upstream

    def _compile_binary(self) -> Path:
        """
        Compile a tuned stream binary into the workspace.
        """
        src = self._upstream_stream_c()
        dst_src = self.workspace_src_dir / "stream.c"
        shutil.copy2(src, dst_src)

        out_path = self.workspace_bin_dir / "stream"

        cflags = [
            "-O3",
            "-fopenmp",
            f"-DSTREAM_ARRAY_SIZE={self.config.stream_array_size}",
            f"-DNTIMES={self.config.ntimes}",
        ]

        # For extremely large static arrays on amd64, relocations can fail without -mcmodel=large.
        bytes_needed = 3 * self.config.stream_array_size * 8
        if bytes_needed >= 2_000_000_000:
            cflags.append("-mcmodel=large")

        cmd = ["gcc", *cflags, str(dst_src), "-o", str(out_path)]
        logger.info("Compiling tuned STREAM: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to compile STREAM (rc={result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        out_path.chmod(0o755)
        return out_path

    def _ensure_binary(self) -> bool:
        if self._needs_recompile():
            try:
                self.stream_path = self._compile_binary()
                self.working_dir = self.stream_path.parent
                return True
            except Exception as exc:
                self._result = {"error": str(exc), "returncode": -2}
                logger.error("Failed to compile STREAM: %s", exc)
                return False

        # Prefer a tuned/workspace binary if it exists.
        if self.stream_path.exists() and os.access(self.stream_path, os.X_OK):
            return True

        # Fall back to system-installed binary (e.g., from stream-benchmark .deb).
        if self.system_stream_path.exists() and os.access(self.system_stream_path, os.X_OK):
            self.stream_path = self.system_stream_path
            self.working_dir = self.system_stream_path.parent
            return True

        self._result = {
            "error": "stream binary missing; install stream-benchmark .deb or enable recompilation with gcc present",
            "returncode": -1,
        }
        logger.error(self._result["error"])
        return False

    def prepare(self) -> None:
        if self._prepared:
            return
        if not self._ensure_binary():
            raise RuntimeError("Failed to prepare STREAM binary")
        self._prepared = True

    def _launcher_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.config.threads > 0:
            env["OMP_NUM_THREADS"] = str(self.config.threads)
        return env

    def _build_command(self) -> list[str]:
        cmd: list[str] = []
        if self.config.use_numactl:
            cmd.extend(["numactl", *self.config.numactl_args])
        cmd.append(str(self.stream_path))
        return cmd

    def _run_command(self) -> None:
        try:
            if not self._ensure_binary():
                return

            cmd = self._build_command()
            logger.info("Running: %s", " ".join(cmd))

            self._process = subprocess.Popen(
                cmd,
                cwd=self.working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=self._launcher_env(),
            )

            timeout_s = self.config.expected_runtime_seconds + self.config.timeout_buffer
            stdout, stderr = self._process.communicate(timeout=timeout_s)
            metrics = self._parse_output(stdout or "")

            self._result = {
                "returncode": self._process.returncode,
                "stdout": stdout or "",
                "stderr": stderr or "",
                "command": " ".join(cmd),
                "stream_version": STREAM_VERSION,
                "upstream_commit": UPSTREAM_COMMIT,
                "stream_array_size": self.config.stream_array_size,
                "ntimes": self.config.ntimes,
                "threads": self.config.threads,
                "max_retries": self.config.max_retries,
                "tags": self.config.tags,
                **metrics,
            }

            if self._process.returncode != 0 and "error" not in self._result:
                self._result["error"] = f"STREAM exited with return code {self._process.returncode}"

        except subprocess.TimeoutExpired:
            logger.error("STREAM timed out; terminating process")
            if self._process:
                self._process.kill()
                self._process.wait()
            self._result = {"error": f"Timeout after {timeout_s}s", "returncode": -1}
        except Exception as exc:
            logger.error("Execution error: %s", exc)
            self._result = {"error": str(exc), "returncode": -2}
        finally:
            self._process = None
            self._is_running = False

    def _parse_output(self, output: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {}

        # Example table lines:
        # Copy:       12345.6     0.0012     0.0011     0.0013
        row = re.compile(
            r"^(Copy|Scale|Add|Triad):\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*$"
        )
        for raw in output.splitlines():
            line = raw.strip()
            match = row.match(line)
            if match:
                name = match.group(1).lower()
                try:
                    metrics[f"{name}_best_rate_mb_s"] = float(match.group(2))
                    metrics[f"{name}_avg_time_s"] = float(match.group(3))
                    metrics[f"{name}_min_time_s"] = float(match.group(4))
                    metrics[f"{name}_max_time_s"] = float(match.group(5))
                except ValueError:
                    continue

            if "Solution Validates" in line:
                metrics["validated"] = True
            if line.startswith("Failed Validation"):
                metrics["validated"] = False

        return metrics

    def _stop_workload(self) -> None:
        proc = self._process
        if proc and proc.poll() is None:
            logger.info("Terminating STREAM workload")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing STREAM workload")
                proc.kill()
                proc.wait()
        self._process = None


class StreamPlugin(WorkloadPlugin):
    """STREAM Plugin definition."""

    @property
    def name(self) -> str:
        return "stream"

    @property
    def description(self) -> str:
        return "STREAM 5.10 memory bandwidth benchmark (OpenMP)"

    @property
    def config_cls(self) -> Type[StreamConfig]:
        return StreamConfig

    def create_generator(self, config: StreamConfig) -> StreamGenerator:
        return StreamGenerator(config)

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[StreamConfig]:
        import multiprocessing

        cpu_count = multiprocessing.cpu_count()

        if level == WorkloadIntensity.LOW:
            return StreamConfig(threads=1)
        if level == WorkloadIntensity.MEDIUM:
            return StreamConfig(threads=cpu_count, stream_array_size=DEFAULT_STREAM_ARRAY_SIZE)
        if level == WorkloadIntensity.HIGH:
            return StreamConfig(threads=cpu_count, stream_array_size=20_000_000, ntimes=20)
        return None

    def get_required_apt_packages(self) -> List[str]:
        return ["libgomp1", "gcc", "make", "numactl"]

    def get_required_local_tools(self) -> List[str]:
        return ["gcc", "numactl"]

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

    def get_ansible_setup_path(self) -> Optional[Path]:
        return Path(__file__).parent / "ansible" / "setup.yml"

    def export_results_to_csv(
        self,
        results: List[dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> List[Path]:
        import pandas as pd

        rows: list[dict[str, Any]] = []
        for entry in results:
            gen_result = entry.get("generator_result") or {}
            rows.append(
                {
                    "run_id": run_id,
                    "workload": test_name,
                    "repetition": entry.get("repetition"),
                    "duration_seconds": entry.get("duration_seconds"),
                    "success": entry.get("success"),
                    "returncode": gen_result.get("returncode"),
                    "stream_array_size": gen_result.get("stream_array_size"),
                    "ntimes": gen_result.get("ntimes"),
                    "threads": gen_result.get("threads"),
                    "validated": gen_result.get("validated"),
                    "copy_best_rate_mb_s": gen_result.get("copy_best_rate_mb_s"),
                    "scale_best_rate_mb_s": gen_result.get("scale_best_rate_mb_s"),
                    "add_best_rate_mb_s": gen_result.get("add_best_rate_mb_s"),
                    "triad_best_rate_mb_s": gen_result.get("triad_best_rate_mb_s"),
                    "max_retries": gen_result.get("max_retries"),
                    "tags": gen_result.get("tags"),
                }
            )

        if not rows:
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{test_name}_plugin.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        return [csv_path]


PLUGIN = StreamPlugin()

