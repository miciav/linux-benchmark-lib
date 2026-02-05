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
from typing import Any, List, Optional

from pydantic import Field, model_validator

from lb_common.api import WorkloadError
from ...base_generator import CommandGenerator
from ...interface import BasePluginConfig, WorkloadIntensity, SimpleWorkloadPlugin

logger = logging.getLogger(__name__)

STREAM_VERSION = "5.10"
UPSTREAM_COMMIT = "6703f7504a38a8da96b353cadafa64d3c2d7a2d3"

UPSTREAM_STREAM_ARRAY_SIZE = 10_000_000
UPSTREAM_NTIMES = 10

DEFAULT_STREAM_ARRAY_SIZE = UPSTREAM_STREAM_ARRAY_SIZE
DEFAULT_NTIMES = 100


class StreamConfig(BasePluginConfig):
    """Configuration for STREAM benchmark."""

    stream_array_size: int = Field(
        default=DEFAULT_STREAM_ARRAY_SIZE,
        gt=0,
        description=(
            "STREAM_ARRAY_SIZE (compile-time); number of elements per array"
        ),
    )
    ntimes: int = Field(
        default=DEFAULT_NTIMES,
        gt=1,
        description="NTIMES (compile-time); number of iterations per kernel",
    )
    recompile: bool = Field(
        default=False,
        description=(
            "Force recompiling the stream binary into the workspace before running"
        ),
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
        description=(
            "Custom workspace directory for tuned binaries and temporary artifacts"
        ),
    )
    expected_runtime_seconds: int = Field(
        default=60,
        gt=0,
        description="Expected runtime used to derive a timeout hint",
    )
    compilers: List[str] = Field(
        default_factory=lambda: ["gcc"],
        description=(
            "Compilers to run (e.g., ['gcc'], ['icc'], ['gcc', 'icc'])"
        ),
    )
    allow_missing_compilers: bool = Field(
        default=False,
        description="Skip missing compilers instead of failing the run",
    )

    @model_validator(mode="after")
    def normalize_compilers(self) -> "StreamConfig":
        compilers = [
            str(item).strip().lower()
            for item in self.compilers
            if str(item).strip()
        ]
        unique: list[str] = []
        for compiler in compilers:
            if compiler not in unique:
                unique.append(compiler)
        if not unique:
            raise ValueError(
                "StreamConfig.compilers must include at least one compiler"
            )
        self.compilers = unique
        return self


class StreamGenerator(CommandGenerator):
    """Generates and runs STREAM workload."""

    def __init__(self, config: StreamConfig, name: str = "StreamGenerator") -> None:
        super().__init__(name, config)

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
        self._compiler_plan: list[str] = list(config.compilers)

    def _needs_recompile(self) -> bool:
        return bool(
            self.config.recompile
            or self.config.stream_array_size != UPSTREAM_STREAM_ARRAY_SIZE
            or self.config.ntimes != UPSTREAM_NTIMES
        )

    def _resolve_oneapi_compiler_binary(self, preferred: list[str]) -> str | None:
        base = Path("/opt/intel/oneapi/compiler")
        if not base.exists():
            return None

        roots = self._oneapi_roots(base)
        return self._find_oneapi_compiler(roots, preferred)

    @staticmethod
    def _oneapi_roots(base: Path) -> list[Path]:
        latest = base / "latest"
        if latest.exists():
            return [latest]
        versions = sorted(
            (path for path in base.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
        return [versions[-1]] if versions else []

    @staticmethod
    def _find_oneapi_compiler(roots: list[Path], preferred: list[str]) -> str | None:
        for candidate in StreamGenerator._iter_oneapi_candidates(roots, preferred):
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    @staticmethod
    def _iter_oneapi_candidates(
        roots: list[Path], preferred: list[str]
    ) -> list[Path]:
        candidates: list[Path] = []
        for root in roots:
            for bin_dir in ("linux/bin/intel64", "linux/bin"):
                bin_root = root / bin_dir
                for name in preferred:
                    candidates.append(bin_root / name)
        return candidates

    def _resolve_compiler_binary(self, compiler: str) -> str | None:
        if compiler == "gcc":
            return shutil.which("gcc")
        if compiler in {"icc", "icx"}:
            preferred = ["icc", "icx"] if compiler == "icc" else ["icx", "icc"]
            return (
                shutil.which(preferred[0])
                or shutil.which(preferred[1])
                or self._resolve_oneapi_compiler_binary(preferred)
            )
        return shutil.which(compiler)

    def _oneapi_version_root(self, compiler_bin: str | None) -> Path | None:
        if not compiler_bin:
            return None
        try:
            path = Path(compiler_bin).resolve()
        except OSError:
            return None
        parts = path.parts
        if "compiler" in parts:
            idx = parts.index("compiler")
            if idx + 1 < len(parts):
                return Path(*parts[: idx + 2])
        return None

    def _oneapi_library_paths(self, compiler_bin: str | None) -> list[str]:
        version_root = self._oneapi_version_root(compiler_bin)
        if version_root is None:
            fallback = Path("/opt/intel/oneapi/compiler/latest")
            if fallback.exists():
                version_root = fallback
        if version_root is None or not version_root.exists():
            return []

        candidates = [
            version_root / "linux" / "compiler" / "lib" / "intel64_lin",
            version_root / "linux" / "compiler" / "lib",
            version_root / "linux" / "lib",
            version_root / "lib",
        ]
        return [str(path) for path in candidates if path.exists()]

    def _openmp_flag(self, compiler_bin: str) -> str:
        compiler_name = Path(compiler_bin).name
        if compiler_name == "icc":
            return "-qopenmp"
        return "-fopenmp"

    def _compiler_label(self, compiler: str) -> str:
        return compiler.replace("/", "_")

    def _compiled_binary_path(self, compiler: str, *, multi: bool) -> Path:
        if compiler == "gcc" and not multi:
            return self.workspace_bin_dir / "stream"
        return self.workspace_bin_dir / f"stream-{self._compiler_label(compiler)}"

    def _compiler_env(self, compiler_bin: str | None) -> dict[str, str]:
        env = os.environ.copy()
        lib_paths = self._oneapi_library_paths(compiler_bin)
        if lib_paths:
            existing = env.get("LD_LIBRARY_PATH")
            env["LD_LIBRARY_PATH"] = (
                ":".join(lib_paths + [existing]) if existing else ":".join(lib_paths)
            )
        return env

    def _validate_environment(self) -> bool:
        compilers = self._resolve_compiler_plan()
        if not compilers:
            return False
        self._compiler_plan = compilers

        if self.config.use_numactl and not shutil.which("numactl"):
            logger.error("numactl not found in PATH")
            return False

        return self._prepare_workspace()

    def _resolve_compiler_plan(self) -> list[str] | None:
        compilers = list(self._compiler_plan)
        if not compilers:
            logger.error("No compilers configured for STREAM")
            return None
        if not self._needs_compile_for_compilers(compilers):
            return compilers

        missing = self._missing_compilers(compilers)
        if not missing:
            return compilers
        if self.config.allow_missing_compilers:
            logger.warning(
                "Skipping missing STREAM compilers: %s", ", ".join(missing)
            )
            available = [c for c in compilers if c not in missing]
            if not available:
                logger.error("No available compilers remain for STREAM")
                return None
            return available
        logger.error("Missing STREAM compilers: %s", ", ".join(missing))
        return None

    def _needs_compile_for_compilers(self, compilers: list[str]) -> bool:
        multi = len(compilers) > 1
        return self._needs_recompile() or multi or any(c != "gcc" for c in compilers)

    def _missing_compilers(self, compilers: list[str]) -> list[str]:
        missing: list[str] = []
        for compiler in compilers:
            if self._resolve_compiler_binary(compiler) is None:
                missing.append(compiler)
        return missing

    def _prepare_workspace(self) -> bool:
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

    def _compile_binary_for_compiler(
        self, compiler_bin: str, output_path: Path
    ) -> Path:
        """Compile a tuned stream binary into the workspace."""
        src = self._upstream_stream_c()
        dst_src = self.workspace_src_dir / "stream.c"
        shutil.copy2(src, dst_src)

        out_path = output_path

        cflags = [
            "-O3",
            self._openmp_flag(compiler_bin),
            f"-DSTREAM_ARRAY_SIZE={self.config.stream_array_size}",
            f"-DNTIMES={self.config.ntimes}",
        ]

        # For extremely large static arrays on amd64, relocations can fail
        # without -mcmodel=large.
        bytes_needed = 3 * self.config.stream_array_size * 8
        if bytes_needed >= 2_000_000_000:
            cflags.append("-mcmodel=large")

        cmd = [compiler_bin, *cflags, str(dst_src), "-o", str(out_path)]
        logger.info("Compiling tuned STREAM: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=self._compiler_env(compiler_bin),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to compile STREAM (rc={result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        out_path.chmod(0o755)
        return out_path

    def _ensure_binary_for_compiler(
        self, compiler: str, compiler_bin: str | None, *, multi: bool
    ) -> Path | None:
        if self._should_compile(compiler, multi=multi):
            return self._compile_for_compiler(compiler, compiler_bin, multi=multi)
        return self._select_existing_binary()

    def _should_compile(self, compiler: str, *, multi: bool) -> bool:
        return self._needs_recompile() or multi or compiler != "gcc"

    def _compile_for_compiler(
        self,
        compiler: str,
        compiler_bin: str | None,
        *,
        multi: bool,
    ) -> Path | None:
        if compiler_bin is None:
            self._result = {"error": f"Compiler '{compiler}' not available"}
            logger.error("Compiler '%s' not available", compiler)
            return None
        try:
            output_path = self._compiled_binary_path(compiler, multi=multi)
            self.stream_path = self._compile_binary_for_compiler(
                compiler_bin, output_path
            )
            self.working_dir = self.stream_path.parent
            return self.stream_path
        except Exception as exc:
            self._result = {"error": str(exc), "returncode": -2}
            logger.error("Failed to compile STREAM (%s): %s", compiler, exc)
            return None

    def _select_existing_binary(self) -> Path | None:
        # Prefer a tuned/workspace binary if it exists.
        if self.stream_path.exists() and os.access(self.stream_path, os.X_OK):
            return self.stream_path

        # Fall back to system-installed binary (e.g., from stream-benchmark .deb).
        if self.system_stream_path.exists() and os.access(
            self.system_stream_path, os.X_OK
        ):
            self.stream_path = self.system_stream_path
            self.working_dir = self.system_stream_path.parent
            return self.stream_path

        self._result = {
            "error": (
                "stream binary missing; install stream-benchmark .deb or enable "
                "recompilation with gcc present"
            ),
            "returncode": -1,
        }
        logger.error(self._result["error"])
        return None

    def prepare(self) -> None:
        if self._prepared:
            return
        if not self._validate_environment():
            raise RuntimeError("STREAM environment validation failed")
        compilers = list(self._compiler_plan)
        multi = len(compilers) > 1
        for compiler in compilers:
            compiler_bin = self._resolve_compiler_binary(compiler)
            stream_path = self._ensure_binary_for_compiler(
                compiler, compiler_bin, multi=multi
            )
            if stream_path is None:
                raise RuntimeError("Failed to prepare STREAM binary")
        self._prepared = True

    def _launcher_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.config.threads > 0:
            env["OMP_NUM_THREADS"] = str(self.config.threads)
        return env

    def _launcher_env_for_compiler(self, compiler_bin: str | None) -> dict[str, str]:
        env = self._launcher_env()
        lib_paths = self._oneapi_library_paths(compiler_bin)
        if lib_paths:
            existing = env.get("LD_LIBRARY_PATH")
            env["LD_LIBRARY_PATH"] = (
                ":".join(lib_paths + [existing]) if existing else ":".join(lib_paths)
            )
        return env

    def _build_command(self) -> list[str]:
        cmd: list[str] = []
        if self.config.use_numactl:
            cmd.extend(["numactl", *self.config.numactl_args])
        cmd.append(str(self.stream_path))
        return cmd

    def _build_command_for_binary(self, stream_path: Path) -> list[str]:
        cmd: list[str] = []
        if self.config.use_numactl:
            cmd.extend(["numactl", *self.config.numactl_args])
        cmd.append(str(stream_path))
        return cmd

    def _popen_kwargs(self, env: dict[str, str] | None = None) -> dict[str, Any]:
        return {
            "cwd": self.working_dir,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "env": env or self._launcher_env(),
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
        metrics = self._parse_output(stdout or "")
        result = super()._build_result(cmd, stdout, stderr, returncode)
        result.update(
            {
                "stream_version": STREAM_VERSION,
                "upstream_commit": UPSTREAM_COMMIT,
                "stream_array_size": self.config.stream_array_size,
                "ntimes": self.config.ntimes,
                "threads": self.config.threads,
                **metrics,
            }
        )
        return result

    def _after_run(
        self,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> None:
        if returncode not in (None, 0) and "error" not in self._result:
            self._result["error"] = f"STREAM exited with return code {returncode}"

    def _run_command(self) -> None:
        compilers = list(self._compiler_plan)
        if not compilers:
            self._is_running = False
            return

        multi = len(compilers) > 1
        compiler_results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for compiler in compilers:
            result, failed = self._run_for_compiler(compiler, multi=multi)
            compiler_results.append(result)
            if failed:
                failures.append(result)
                if not self.config.allow_missing_compilers:
                    break

        self._result = self._build_overall_result(
            compiler_results, failures, multi=multi
        )

    def _run_for_compiler(
        self, compiler: str, *, multi: bool
    ) -> tuple[dict[str, Any], bool]:
        compiler_bin = self._resolve_compiler_binary(compiler)
        stream_path = self._ensure_binary_for_compiler(
            compiler, compiler_bin, multi=multi
        )
        if stream_path is None:
            failure = {
                "compiler": compiler,
                "compiler_bin": compiler_bin,
                "returncode": -2,
                "error": f"Failed to prepare STREAM binary for {compiler}",
            }
            return failure, True

        cmd = self._build_command_for_binary(stream_path)
        self._log_command(cmd)
        stdout, stderr, returncode = self._execute_stream_command(cmd, compiler_bin)
        result = self._build_compiler_result(
            compiler=compiler,
            compiler_bin=compiler_bin,
            cmd=cmd,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )
        failed = returncode not in (None, 0)
        if failed:
            self._log_failure(returncode, stdout, stderr, cmd)
            if "error" not in result:
                result["error"] = f"STREAM exited with return code {returncode}"
        else:
            self._emit_table_event(compiler, stdout)
        return result, failed

    def _execute_stream_command(
        self, cmd: list[str], compiler_bin: str | None
    ) -> tuple[str, str, int | None]:
        try:
            self._active_timeout = self._timeout_seconds()
            env = self._launcher_env_for_compiler(compiler_bin)
            self._process = subprocess.Popen(cmd, **self._popen_kwargs(env))
            stdout, stderr = self._consume_process_output(self._process)
            return stdout, stderr, self._process.returncode
        except subprocess.TimeoutExpired:
            timeout = self._timeout_seconds()
            logger.error(
                "%s timed out after %s seconds. Terminating process.",
                self.name,
                timeout,
            )
            return "", "", -1
        except Exception as exc:
            logger.error("Error running %s: %s", self.name, exc)
            return "", str(exc), -2
        finally:
            self._process = None
            self._active_timeout = None

    def _build_overall_result(
        self,
        compiler_results: list[dict[str, Any]],
        failures: list[dict[str, Any]],
        *,
        multi: bool,
    ) -> dict[str, Any]:
        overall_rc = 0 if not failures else failures[0].get("returncode") or 1
        result = {
            "returncode": overall_rc,
            "command": "stream (multi)"
            if multi
            else compiler_results[0].get("command"),
            "stream_version": STREAM_VERSION,
            "upstream_commit": UPSTREAM_COMMIT,
            "stream_array_size": self.config.stream_array_size,
            "ntimes": self.config.ntimes,
            "threads": self.config.threads,
            "compiler_results": compiler_results,
            "compiler": compiler_results[0].get("compiler")
            if compiler_results
            else None,
            "compiler_bin": compiler_results[0].get("compiler_bin")
            if compiler_results
            else None,
        }
        if failures:
            result["error"] = "STREAM failed for one or more compilers"
            self._set_error(
                WorkloadError(
                    "STREAM failed for one or more compilers",
                    context={"compilers": [f["compiler"] for f in failures]},
                )
            )
        return result

    def _parse_output(self, output: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {}

        # Example table lines:
        # Copy:       12345.6     0.0012     0.0011     0.0013
        row = re.compile(
            r"^(Copy|Scale|Add|Triad):\s+([0-9.]+)\s+([0-9.]+)\s+"
            r"([0-9.]+)\s+([0-9.]+)\s*$"
        )
        for raw in output.splitlines():
            line = raw.strip()
            self._parse_metrics_line(line, row, metrics)
            self._parse_validation_line(line, metrics)

        return metrics

    @staticmethod
    def _parse_metrics_line(
        line: str, row: re.Pattern[str], metrics: dict[str, Any]
    ) -> None:
        match = row.match(line)
        if not match:
            return
        name = match.group(1).lower()
        try:
            metrics[f"{name}_best_rate_mb_s"] = float(match.group(2))
            metrics[f"{name}_avg_time_s"] = float(match.group(3))
            metrics[f"{name}_min_time_s"] = float(match.group(4))
            metrics[f"{name}_max_time_s"] = float(match.group(5))
        except ValueError:
            return

    @staticmethod
    def _parse_validation_line(line: str, metrics: dict[str, Any]) -> None:
        if "Solution Validates" in line:
            metrics["validated"] = True
            return
        if line.startswith("Failed Validation"):
            metrics["validated"] = False

    def _extract_result_table(self, output: str) -> str | None:
        lines = output.splitlines()
        header_idx = self._find_table_header(lines)
        if header_idx is None:
            return None
        start_idx = self._table_start_index(lines, header_idx)
        end_idx = self._table_end_index(lines, header_idx)
        table_lines = lines[start_idx : end_idx + 1]
        return "\n".join(table_lines) if table_lines else None

    @staticmethod
    def _find_table_header(lines: list[str]) -> int | None:
        header_re = re.compile(
            r"^Function\s+Best Rate MB/s\s+Avg time\s+Min time\s+Max time\s*$"
        )
        for idx, raw in enumerate(lines):
            if header_re.match(raw.strip()):
                return idx
        return None

    @staticmethod
    def _table_start_index(lines: list[str], header_idx: int) -> int:
        if header_idx > 0 and lines[header_idx - 1].strip().startswith("---"):
            return header_idx - 1
        return header_idx

    @staticmethod
    def _table_end_index(lines: list[str], header_idx: int) -> int:
        for idx in range(header_idx + 1, len(lines)):
            if lines[idx].strip().startswith("---"):
                return idx
        return min(header_idx + 5, len(lines) - 1)

    def _emit_table_event(self, compiler: str, output: str) -> None:
        table = self._extract_result_table(output)
        if not table:
            return
        logger.info("STREAM results (%s):\n%s", compiler, table)

    def _build_compiler_result(
        self,
        *,
        compiler: str,
        compiler_bin: str | None,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> dict[str, Any]:
        metrics = self._parse_output(stdout or "")
        result = super()._build_result(cmd, stdout, stderr, returncode)
        result.update(
            {
                "compiler": compiler,
                "compiler_bin": compiler_bin,
                "stream_version": STREAM_VERSION,
                "upstream_commit": UPSTREAM_COMMIT,
                "stream_array_size": self.config.stream_array_size,
                "ntimes": self.config.ntimes,
                "threads": self.config.threads,
                **metrics,
            }
        )
        return result

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


class StreamPlugin(SimpleWorkloadPlugin):
    """STREAM Plugin definition."""

    NAME = "stream"
    DESCRIPTION = "STREAM 5.10 memory bandwidth benchmark (OpenMP)"
    CONFIG_CLS = StreamConfig
    GENERATOR_CLS = StreamGenerator
    REQUIRED_APT_PACKAGES = ["libgomp1", "gcc", "make", "numactl"]
    REQUIRED_LOCAL_TOOLS = ["gcc", "numactl"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"
    TEARDOWN_PLAYBOOK = Path(__file__).parent / "ansible" / "teardown.yml"
    PRESET_COMPILERS = ["gcc", "icc"]

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[StreamConfig]:
        import multiprocessing

        cpu_count = multiprocessing.cpu_count()
        preset_kwargs = self._preset_kwargs()
        presets = {
            WorkloadIntensity.LOW: self._preset_low,
            WorkloadIntensity.MEDIUM: self._preset_medium,
            WorkloadIntensity.HIGH: self._preset_high,
        }
        builder = presets.get(level)
        if not builder:
            return None
        return builder(cpu_count, preset_kwargs)

    def _preset_kwargs(self) -> dict[str, Any]:
        return {
            "compilers": list(self.PRESET_COMPILERS),
            "allow_missing_compilers": True,
        }

    @staticmethod
    def _preset_low(cpu_count: int, preset_kwargs: dict[str, Any]) -> StreamConfig:
        return StreamConfig(threads=1, **preset_kwargs)

    @staticmethod
    def _preset_medium(cpu_count: int, preset_kwargs: dict[str, Any]) -> StreamConfig:
        return StreamConfig(
            threads=cpu_count,
            stream_array_size=DEFAULT_STREAM_ARRAY_SIZE,
            **preset_kwargs,
        )

    @staticmethod
    def _preset_high(cpu_count: int, preset_kwargs: dict[str, Any]) -> StreamConfig:
        return StreamConfig(
            threads=cpu_count,
            stream_array_size=20_000_000,
            ntimes=20,
            **preset_kwargs,
        )

    def get_ansible_setup_extravars(self) -> dict[str, Any]:
        return {"stream_install_intel_compiler": True}

    def get_ansible_teardown_extravars(self) -> dict[str, Any]:
        return {"stream_cleanup_intel_compiler": True}

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
            rows.extend(self._rows_for_entry(entry, run_id, test_name))

        if not rows:
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{test_name}_plugin.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        return [csv_path]

    def _rows_for_entry(
        self, entry: dict[str, Any], run_id: str, test_name: str
    ) -> list[dict[str, Any]]:
        gen_result = entry.get("generator_result") or {}
        compiler_results = gen_result.get("compiler_results") or []
        if compiler_results:
            return [
                self._build_csv_row(entry, result, run_id, test_name)
                for result in compiler_results
            ]
        return [self._build_csv_row(entry, gen_result, run_id, test_name)]

    @staticmethod
    def _time_ms(value: Any) -> float | None:
        try:
            return None if value is None else float(value) * 1000.0
        except (TypeError, ValueError):
            return None

    def _build_csv_row(
        self,
        entry: dict[str, Any],
        result: dict[str, Any],
        run_id: str,
        test_name: str,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "workload": test_name,
            "repetition": entry.get("repetition"),
            "duration_seconds": entry.get("duration_seconds"),
            "success": entry.get("success"),
            "compiler": result.get("compiler"),
            "compiler_bin": result.get("compiler_bin"),
            "returncode": result.get("returncode"),
            "stream_array_size": result.get("stream_array_size"),
            "ntimes": result.get("ntimes"),
            "threads": result.get("threads"),
            "validated": result.get("validated"),
            "copy_best_rate_mb_s": result.get("copy_best_rate_mb_s"),
            "copy_avg_time_s": result.get("copy_avg_time_s"),
            "copy_min_time_s": result.get("copy_min_time_s"),
            "copy_max_time_s": result.get("copy_max_time_s"),
            "copy_avg_time_ms": self._time_ms(result.get("copy_avg_time_s")),
            "copy_min_time_ms": self._time_ms(result.get("copy_min_time_s")),
            "copy_max_time_ms": self._time_ms(result.get("copy_max_time_s")),
            "scale_best_rate_mb_s": result.get("scale_best_rate_mb_s"),
            "scale_avg_time_s": result.get("scale_avg_time_s"),
            "scale_min_time_s": result.get("scale_min_time_s"),
            "scale_max_time_s": result.get("scale_max_time_s"),
            "scale_avg_time_ms": self._time_ms(result.get("scale_avg_time_s")),
            "scale_min_time_ms": self._time_ms(result.get("scale_min_time_s")),
            "scale_max_time_ms": self._time_ms(result.get("scale_max_time_s")),
            "add_best_rate_mb_s": result.get("add_best_rate_mb_s"),
            "add_avg_time_s": result.get("add_avg_time_s"),
            "add_min_time_s": result.get("add_min_time_s"),
            "add_max_time_s": result.get("add_max_time_s"),
            "add_avg_time_ms": self._time_ms(result.get("add_avg_time_s")),
            "add_min_time_ms": self._time_ms(result.get("add_min_time_s")),
            "add_max_time_ms": self._time_ms(result.get("add_max_time_s")),
            "triad_best_rate_mb_s": result.get("triad_best_rate_mb_s"),
            "triad_avg_time_s": result.get("triad_avg_time_s"),
            "triad_min_time_s": result.get("triad_min_time_s"),
            "triad_max_time_s": result.get("triad_max_time_s"),
            "triad_avg_time_ms": self._time_ms(result.get("triad_avg_time_s")),
            "triad_min_time_ms": self._time_ms(result.get("triad_min_time_s")),
            "triad_max_time_ms": self._time_ms(result.get("triad_max_time_s")),
            "max_retries": result.get("max_retries"),
            "tags": result.get("tags"),
        }


PLUGIN = StreamPlugin()
