"""
Geekbench workload plugin.

This plugin downloads and runs Geekbench 6 CPU benchmark. It supports optional
license unlocking and JSON export of results. Network access is only needed to
download the tarball on first run.
"""

from __future__ import annotations

import logging
import os
import platform
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import urlparse
from typing import List, Optional, Type, Any, Tuple, Dict

from pydantic import Field

from ...plugin_system.interface import BasePluginConfig, WorkloadPlugin, WorkloadIntensity
from ...plugin_system.base_generator import BaseGenerator

logger = logging.getLogger(__name__)


def _default_download_url(version: str) -> str:
    """Return the default download URL for the given Geekbench version."""
    return f"https://cdn.geekbench.com/Geekbench-{version}-Linux.tar.gz"


def _arch_suffix() -> str:
    """Return the Geekbench archive suffix for the current architecture."""
    machine = platform.machine().lower()
    if "aarch64" in machine or "arm64" in machine or machine.startswith("arm"):
        return "LinuxARM64"
    return "Linux"


class GeekbenchConfig(BasePluginConfig):
    """Configuration for Geekbench."""

    version: str = Field(default="6.3.0", min_length=1)
    download_url: str | None = Field(default=None, description="Override Geekbench tarball URL.")
    download_checksum: str | None = Field(
        default=None, description="Optional sha256 hex for archive validation."
    )
    workdir: Path = Field(default=Path("/opt/geekbench"))
    output_dir: Path = Field(default=Path("/tmp"))
    license_key: str | None = Field(default=None)
    skip_cleanup: bool = Field(default=True)
    run_gpu: bool = Field(default=False)
    extra_args: list[str] = Field(default_factory=list)
    arch_override: str | None = Field(default=None)
    expected_runtime_seconds: int = Field(default=1800, gt=0)
    debug: bool = Field(default=False)


class GeekbenchGenerator(BaseGenerator):
    """Generator that runs Geekbench CPU benchmark."""

    def __init__(self, config: GeekbenchConfig):
        super().__init__("GeekbenchGenerator")
        self.config = config
        self._process: Optional[subprocess.Popen[str]] = None
        self._download_ready: bool = False
        self._download_error: Optional[str] = None
        self._export_supported: bool = True
        # Allow long-running benchmark; runner will extend duration based on this hint.
        timeout_env = os.environ.get("LB_GEEKBENCH_TIMEOUT")
        if timeout_env:
            try:
                self.expected_runtime_seconds = int(timeout_env)
            except ValueError:
                self.expected_runtime_seconds = int(config.expected_runtime_seconds)
        else:
            self.expected_runtime_seconds = int(config.expected_runtime_seconds)

    def _validate_environment(self) -> bool:
        """Ensure required tools and paths are available."""
        for tool in ("curl", "wget", "tar"):
            if shutil.which(tool) is None:
                logger.error("Required tool missing: %s", tool)
                return False
        for path in (self.config.workdir, self.config.output_dir):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.error("Path %s not writable: %s", path, exc)
                return False
        return True

    def _run_command(self) -> None:
        """Download and execute Geekbench."""
        if not self._validate_environment():
            self._result = {"error": "Environment validation failed"}
            self._is_running = False
            return

        executable: Path | None = None
        archive_path: Path | None = None
        extract_dir: Path | None = None
        try:
            executable, archive_path, extract_dir = self._prepare_geekbench()
            export_path = self.config.output_dir / f"geekbench_result_{time.time_ns()}.json"

            cmd: List[str] = [str(executable)]
            if self.config.license_key:
                cmd.extend(["--unlock", self.config.license_key])
            if self.config.run_gpu:
                cmd.append("--compute")
            if self._export_supported:
                cmd.extend(["--export-json", str(export_path)])
            else:
                cmd.append("--cpu")
            if self.config.extra_args:
                cmd.extend(self.config.extra_args)

            env = os.environ.copy()
            if self.config.debug:
                logger.info("Running Geekbench command: %s", " ".join(cmd))

            run = self._execute_process(cmd, env, executable.parent)

            log_path = self.config.output_dir / "geekbench.log"
            try:
                log_path.write_text((run.stdout or "") + "\n" + (run.stderr or ""))
            except Exception:  # pragma: no cover - best effort
                pass

            result_payload: dict[str, Any] = {
                "stdout": run.stdout or "",
                "stderr": run.stderr or "",
                "returncode": run.returncode,
                "command": " ".join(cmd),
                "log_path": str(log_path),
            }
            if self._export_supported:
                result_payload["json_result"] = str(export_path)
            else:
                result_payload["export_json_supported"] = False
            self._result = result_payload

            # Fallback: if export-json is unsupported (Pro-only) retry without it.
            export_failed = self._export_supported and not export_path.exists()
            stderr_lower = (run.stderr or "").lower()
            export_flag_error = (
                "export-json" in stderr_lower
                or "unknown option" in stderr_lower
                or "unrecognized option" in stderr_lower
                or "invalid option" in stderr_lower
            )
            if self._export_supported and (run.returncode != 0 or export_failed or export_flag_error):
                fallback_cmd = [str(executable)]
                if self.config.run_gpu:
                    fallback_cmd.append("--compute")
                fallback_cmd.append("--cpu")
                if self.config.extra_args:
                    fallback_cmd.extend(self.config.extra_args)
                fallback = self._execute_process(fallback_cmd, env, executable.parent)
                try:
                    log_path.write_text((fallback.stdout or "") + "\n" + (fallback.stderr or ""))
                except Exception:
                    pass
                self._result = {
                    "stdout": fallback.stdout or "",
                    "stderr": fallback.stderr or "",
                    "returncode": fallback.returncode,
                    "command": " ".join(fallback_cmd),
                    "log_path": str(log_path),
                    "export_json_supported": False,
                    "original_returncode": run.returncode,
                }
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Geekbench execution error: %s", exc)
            self._result = {"error": str(exc)}
            self._download_error = str(exc)
        finally:
            if not self.config.skip_cleanup and extract_dir:
                try:
                    shutil.rmtree(extract_dir, ignore_errors=True)
                except Exception:  # pragma: no cover - best effort
                    pass
            if not self.config.skip_cleanup and archive_path:
                archive_path.unlink(missing_ok=True)
            self._is_running = False

    def _execute_process(self, cmd: List[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
        """Run Geekbench command with terminable process to allow stop()."""
        timeout_s = self.expected_runtime_seconds
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=env,
        )
        self._process = proc
        try:
            try:
                stdout, stderr = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    stdout, stderr = proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate()
                return subprocess.CompletedProcess(cmd, proc.returncode if proc.returncode is not None else -9, stdout=stdout, stderr=stderr)
        finally:
            self._process = None
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout=stdout, stderr=stderr)

    def _prepare_geekbench(self) -> Tuple[Path, Path, Path]:
        """Ensure Geekbench is downloaded and extracted; return executable and asset paths."""
        if self._download_error:
            raise RuntimeError(self._download_error)

        version = self.config.version
        url = self.config.download_url or _default_download_url(version)

        # Resolve architecture suffix (config override > explicit URL hint > autodetect)
        suffix = None
        if self.config.arch_override:
            override = self.config.arch_override.lower()
            if override in ("arm64", "aarch64", "arm", "linuxarm64"):
                suffix = "LinuxARM64"
            else:
                suffix = "Linux"
        elif "LinuxARM64" in url or url.endswith("ARM64.tar.gz") or "ARM64" in url:
            suffix = "LinuxARM64"
        else:
            suffix = _arch_suffix()

        # Pick the appropriate download URL
        if not self.config.download_url:
            if suffix == "LinuxARM64":
                # Official ARM preview build
                url = f"https://cdn.geekbench.com/Geekbench-{version}-LinuxARMPreview.tar.gz"
            else:
                url = f"https://cdn.geekbench.com/Geekbench-{version}-{suffix}.tar.gz"

        archive_name = Path(urlparse(url).path).name or f"Geekbench-{version}-{suffix}.tar.gz"
        archive_path = self.config.workdir / archive_name
        stem = archive_name[:-7] if archive_name.endswith(".tar.gz") else archive_name
        extract_dir = self.config.workdir / stem
        executable = extract_dir / "geekbench6"
        if self.config.run_gpu:
            executable = extract_dir / "geekbench6_compute"

        # Preview builds do not support --export-json
        if "preview" in archive_name.lower():
            self._export_supported = False

        if executable.exists():
            self._download_ready = True
            return executable, archive_path, extract_dir

        # Download
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
        dl_cmd = ["curl", "-fL", "--retry", "3", "--retry-delay", "1", "-sS", "-o", str(tmp_path), url]
        completed = subprocess.run(dl_cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            msg = completed.stderr or completed.stdout or "download failed"
            # Special-case 404 on ARM to provide clearer guidance
            if "404" in msg and suffix == "LinuxARM64" and not self.config.download_url:
                raise RuntimeError(
                    "Geekbench Linux ARM64 binary not available (404). "
                    "Specify a valid download_url or run under an amd64 container/host."
                )
            raise RuntimeError(f"Failed to download Geekbench: {msg}")

        # Optional checksum validation
        if self.config.download_checksum:
            try:
                import hashlib

                digest = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
                if digest.lower() != self.config.download_checksum.lower():
                    tmp_path.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"Geekbench checksum mismatch for {archive_name}: expected "
                        f"{self.config.download_checksum}, got {digest}"
                    )
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(f"Geekbench checksum validation failed: {exc}") from exc

        # Basic gzip magic check to fail fast on HTML/error responses
        try:
            with tmp_path.open("rb") as fh:
                magic = fh.read(2)
            if magic != b"\x1f\x8b":
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(f"Downloaded file is not a gzip archive from {url}")
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_path), archive_path)

        # Extract
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=self.config.workdir)
        except Exception as exc:
            archive_path.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to extract Geekbench archive: {exc}") from exc

        if not executable.exists():
            raise RuntimeError(f"Geekbench executable not found at {executable}")

        executable.chmod(0o755)
        self._download_ready = True
        return executable, archive_path, extract_dir

    def _stop_workload(self) -> None:
        """Terminate the Geekbench process if it's still running."""
        proc = self._process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._process = None


class GeekbenchPlugin(WorkloadPlugin):
    """Plugin wrapper for Geekbench."""

    @property
    def name(self) -> str:
        return "geekbench"

    @property
    def description(self) -> str:
        return "Geekbench 6 CPU benchmark"

    @property
    def config_cls(self) -> Type[GeekbenchConfig]:
        return GeekbenchConfig

    def create_generator(self, config: GeekbenchConfig | dict) -> GeekbenchGenerator:
        if isinstance(config, dict):
            config = GeekbenchConfig(**config)
        return GeekbenchGenerator(config)

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[GeekbenchConfig]:
        if level == WorkloadIntensity.LOW:
            return GeekbenchConfig(skip_cleanup=True, run_gpu=False)
        if level == WorkloadIntensity.MEDIUM:
            return GeekbenchConfig(skip_cleanup=True, run_gpu=False)
        if level == WorkloadIntensity.HIGH:
            return GeekbenchConfig(skip_cleanup=False, run_gpu=False)
        return None

    def get_required_apt_packages(self) -> List[str]:
        return ["curl", "wget", "tar", "ca-certificates", "sysstat"]

    def get_required_local_tools(self) -> List[str]:
        return ["curl", "wget", "tar"]

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

    def get_ansible_setup_path(self) -> Optional[Path]:
        return Path(__file__).parent / "ansible" / "setup.yml"

    def get_ansible_teardown_path(self) -> Optional[Path]:
        return None

    def export_results_to_csv(
        self,
        results: List[Dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> List[Path]:
        """
        Export Geekbench summary scores to CSV.

        When a Geekbench JSON export is available, extract overall single/multi-core
        scores plus optional subtest scores. Falls back to a minimal flattened CSV
        if parsing fails.
        """
        import pandas as pd

        def _normalize_key(key: str) -> str:
            return key.lower().replace("-", "_").replace(" ", "_")

        def _coerce_number(value: Any) -> Optional[float]:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.strip())
                except Exception:
                    return None
            return None

        def _find_first_score(node: Any, keys: set[str]) -> Optional[float]:
            if isinstance(node, dict):
                for k, v in node.items():
                    nk = _normalize_key(str(k))
                    if nk in keys:
                        num = _coerce_number(v)
                        if num is not None:
                            return num
                    found = _find_first_score(v, keys)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for item in node:
                    found = _find_first_score(item, keys)
                    if found is not None:
                        return found
            return None

        def _find_first_value(node: Any, keys: set[str]) -> Any:
            if isinstance(node, dict):
                for k, v in node.items():
                    nk = _normalize_key(str(k))
                    if nk in keys:
                        return v
                    found = _find_first_value(v, keys)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for item in node:
                    found = _find_first_value(item, keys)
                    if found is not None:
                        return found
            return None

        def _collect_subtests(node: Any) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            if isinstance(node, list):
                # Candidate list of subtests.
                if all(isinstance(i, dict) for i in node):
                    for item in node:
                        name = item.get("name") or item.get("benchmark_name") or item.get("workload")
                        score = item.get("score") or item.get("result") or item.get("value")
                        num = _coerce_number(score)
                        if name and num is not None:
                            rows.append({"subtest": str(name), "score": num})
                for item in node:
                    rows.extend(_collect_subtests(item))
            elif isinstance(node, dict):
                for v in node.values():
                    rows.extend(_collect_subtests(v))
            return rows

        summary_rows: list[dict[str, Any]] = []
        subtest_rows: list[dict[str, Any]] = []

        single_keys = {
            "single_core_score",
            "single_core",
            "single_score",
            "single",
            "cpu_single_core_score",
            "singlecore_score",
        }
        multi_keys = {
            "multi_core_score",
            "multi_core",
            "multi_score",
            "multi",
            "cpu_multi_core_score",
            "multicore_score",
        }
        version_keys = {"geekbench_version", "version"}

        output_dir.mkdir(parents=True, exist_ok=True)

        for entry in results:
            rep = entry.get("repetition")
            gen_result = entry.get("generator_result") or {}
            json_path: Optional[Path] = None

            # Prefer explicit json_result from generator.
            raw_json = gen_result.get("json_result")
            if isinstance(raw_json, str):
                candidate = Path(raw_json)
                if candidate.exists():
                    json_path = candidate
                else:
                    local_candidate = output_dir / candidate.name
                    if local_candidate.exists():
                        json_path = local_candidate

            # Fallback to any json in workload output dir.
            if json_path is None:
                candidates = list(output_dir.glob("geekbench*.json")) + list(output_dir.glob("*geekbench*.json"))
                if candidates:
                    json_path = candidates[0]

            payload: dict[str, Any] | None = None
            if json_path:
                try:
                    payload = pd.read_json(json_path, typ="series").to_dict()  # type: ignore[arg-type]
                except Exception:
                    try:
                        import json as _json

                        payload = _json.loads(json_path.read_text())
                    except Exception:
                        payload = None

            single_score = _find_first_score(payload, single_keys) if payload else None
            multi_score = _find_first_score(payload, multi_keys) if payload else None
            gb_version_raw = _find_first_value(payload, version_keys) if payload else None
            gb_version = (
                str(gb_version_raw)
                if gb_version_raw is not None and gb_version_raw != ""
                else None
            )

            summary_rows.append(
                {
                    "run_id": run_id,
                    "workload": test_name,
                    "repetition": rep,
                    "returncode": gen_result.get("returncode"),
                    "success": entry.get("success"),
                    "duration_seconds": entry.get("duration_seconds"),
                    "single_core_score": single_score,
                    "multi_core_score": multi_score,
                    "geekbench_version": gb_version
                    or gen_result.get("version")
                    or self.config_cls().version,
                    "export_json_supported": gen_result.get("export_json_supported", True),
                }
            )

            if payload:
                for row in _collect_subtests(payload):
                    subtest_rows.append(
                        {
                            "run_id": run_id,
                            "workload": test_name,
                            "repetition": rep,
                            **row,
                        }
                    )

        if not summary_rows:
            return []

        summary_df = pd.DataFrame(summary_rows)
        csv_paths: list[Path] = []
        summary_path = output_dir / f"{test_name}_plugin.csv"
        summary_df.to_csv(summary_path, index=False)
        csv_paths.append(summary_path)

        if subtest_rows:
            sub_df = pd.DataFrame(subtest_rows)
            sub_path = output_dir / f"{test_name}_subtests.csv"
            sub_df.to_csv(sub_path, index=False)
            csv_paths.append(sub_path)

        return csv_paths


PLUGIN = GeekbenchPlugin()
