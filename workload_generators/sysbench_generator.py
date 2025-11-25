"""
Sysbench workload generator implementation.

Provides a wrapper around common sysbench benchmarks such as CPU, memory,
and file I/O.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Type

from ._base_generator import BaseGenerator
from plugins.interface import WorkloadPlugin


logger = logging.getLogger(__name__)


@dataclass
class SysbenchConfig:
    """Configuration for the sysbench workload generator."""

    benchmark: str = "cpu"  # cpu, memory, fileio, threads, mutex, etc.
    threads: int = 1
    time: int = 60
    events: Optional[int] = 0  # 0 = unlimited; rely on --time
    report_interval: int = 5

    # CPU specific
    cpu_max_prime: int = 20000

    # Memory specific
    memory_block_size: str = "1K"
    memory_total_size: str = "1G"
    memory_access_mode: str = "seq"
    memory_oper: str = "write"

    # File I/O specific
    file_total_size: str = "1G"
    file_test_mode: str = "seqwr"
    file_io_mode: str = "sync"
    prepare_fileio: bool = True
    cleanup_fileio: bool = True

    # Misc
    timeout: Optional[int] = None  # Per-phase timeout; defaults to time+10
    extra_args: List[str] = field(default_factory=list)


class SysbenchGenerator(BaseGenerator):
    """Workload generator using sysbench."""

    def __init__(self, config: SysbenchConfig, name: str = "SysbenchGenerator") -> None:
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen[str]] = None

    def _build_command(self, phase: str = "run") -> List[str]:
        args: List[str] = ["sysbench", self.config.benchmark]
        args.append(f"--threads={self.config.threads}")
        args.append(f"--time={self.config.time}")
        if self.config.events is not None:
            args.append(f"--events={self.config.events}")
        if self.config.report_interval:
            args.append(f"--report-interval={self.config.report_interval}")

        args.extend(self._benchmark_args())
        args.extend(self.config.extra_args)
        args.append(phase)
        return args

    def _benchmark_args(self) -> List[str]:
        """Return benchmark-specific arguments."""
        if self.config.benchmark == "cpu":
            return ["--cpu-max-prime", str(self.config.cpu_max_prime)]
            return [f"--cpu-max-prime={self.config.cpu_max_prime}"]
        if self.config.benchmark == "memory":
            return [
                f"--memory-block-size={self.config.memory_block_size}",
                f"--memory-total-size={self.config.memory_total_size}",
                f"--memory-access-mode={self.config.memory_access_mode}",
                f"--memory-oper={self.config.memory_oper}",
            ]
        if self.config.benchmark == "fileio":
            return [
                f"--file-total-size={self.config.file_total_size}",
                f"--file-test-mode={self.config.file_test_mode}",
                f"--file-io-mode={self.config.file_io_mode}",
            ]
        return []

    def _phase_timeout(self) -> int:
        """Resolve a sensible timeout for a sysbench phase."""
        if self.config.timeout is not None:
            return self.config.timeout
        return self.config.time + 10

    def _execute_phase(self, phase: str) -> dict:
        """Execute a sysbench phase (prepare/run/cleanup)."""
        cmd = self._build_command(phase)
        logger.info("Running command: %s", " ".join(cmd))
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = self._process.communicate(timeout=self._phase_timeout())
            rc = self._process.returncode
        except subprocess.TimeoutExpired:
            logger.error("sysbench phase '%s' timed out after %ss", phase, self._phase_timeout())
            self._process.kill()
            stdout, stderr = self._process.communicate()
            rc = self._process.returncode
            return {
                "command": " ".join(cmd),
                "stdout": stdout,
                "stderr": stderr,
                "returncode": rc,
                "error": "TimeoutExpired",
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error running sysbench phase '%s': %s", phase, exc)
            return {
                "command": " ".join(cmd),
                "stdout": "",
                "stderr": str(exc),
                "returncode": -1,
                "error": str(exc),
            }
        finally:
            self._process = None

        return {
            "command": " ".join(cmd),
            "stdout": stdout,
            "stderr": stderr,
            "returncode": rc,
        }

    def _run_command(self) -> None:
        result: dict = {"phases": {}}
        try:
            if self.config.benchmark == "fileio" and self.config.prepare_fileio:
                result["phases"]["prepare"] = self._execute_phase("prepare")

            run_result = self._execute_phase("run")
            result["phases"]["run"] = run_result
            result["returncode"] = run_result.get("returncode")

            if run_result.get("returncode") not in (0, None):
                self._result = result
                return

            if self.config.benchmark == "fileio" and self.config.cleanup_fileio:
                result["phases"]["cleanup"] = self._execute_phase("cleanup")

        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Sysbench run failed: %s", exc)
            result = {"error": str(exc)}
        finally:
            self._result = result
            self._is_running = False

    def _stop_workload(self) -> None:
        proc = self._process
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _validate_environment(self) -> bool:
        return shutil.which("sysbench") is not None


class SysbenchPlugin(WorkloadPlugin):
    """Plugin definition for Sysbench."""

    @property
    def name(self) -> str:
        return "sysbench"

    @property
    def description(self) -> str:
        return "Versatile benchmark suite (CPU, memory, file I/O)"

    @property
    def config_cls(self) -> Type[SysbenchConfig]:
        return SysbenchConfig

    def create_generator(self, config: SysbenchConfig) -> SysbenchGenerator:
        return SysbenchGenerator(config)

    def get_required_apt_packages(self) -> List[str]:
        return ["sysbench"]


# Exposed plugin instance
PLUGIN = SysbenchPlugin()
