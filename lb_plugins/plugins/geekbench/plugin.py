"""
Geekbench workload plugin.

This plugin downloads and runs Geekbench 6 CPU benchmark. It supports optional
license unlocking and JSON export of results. Network access is only needed to
download the tarball on first run.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import urlparse
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pydantic import Field

from ...interface import BasePluginConfig, SimpleWorkloadPlugin, WorkloadIntensity
from ...base_generator import CommandGenerator, CommandSpec
from ...utils.csv_export import write_csv_rows

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


def _default_geekbench_output_dir() -> Path:
    return Path(tempfile.gettempdir()) / "lb_geekbench"


class GeekbenchConfig(BasePluginConfig):
    """Configuration for Geekbench."""

    version: str = Field(default="6.3.0", min_length=1)
    download_url: str | None = Field(
        default=None, description="Override Geekbench tarball URL."
    )
    download_checksum: str | None = Field(
        default=None, description="Optional sha256 hex for archive validation."
    )
    workdir: Path = Field(default=Path("/opt/geekbench"))
    output_dir: Path = Field(default_factory=_default_geekbench_output_dir)
    license_key: str | None = Field(default=None)
    skip_cleanup: bool = Field(default=True)
    run_gpu: bool = Field(default=False)
    extra_args: list[str] = Field(default_factory=list)
    arch_override: str | None = Field(default=None)
    expected_runtime_seconds: int = Field(default=1800, gt=0)
    debug: bool = Field(default=False)


@dataclass(frozen=True)
class _GeekbenchAssets:
    executable: Path
    archive_path: Path
    extract_dir: Path
    archive_name: str
    export_supported: bool


def _is_arm64_hint(value: str) -> bool:
    upper = value.upper()
    return "LINUXARM64" in upper or "ARM64" in upper


def _resolve_arch_suffix(config: GeekbenchConfig, url_hint: str) -> str:
    if config.arch_override:
        override = config.arch_override.lower()
        if override in ("arm64", "aarch64", "arm", "linuxarm64"):
            return "LinuxARM64"
        return "Linux"
    if _is_arm64_hint(url_hint):
        return "LinuxARM64"
    return _arch_suffix()


def _resolve_download_url(
    config: GeekbenchConfig,
    version: str,
    suffix: str,
) -> str:
    if config.download_url:
        return config.download_url
    if suffix == "LinuxARM64":
        return f"https://cdn.geekbench.com/Geekbench-{version}-LinuxARMPreview.tar.gz"
    return f"https://cdn.geekbench.com/Geekbench-{version}-{suffix}.tar.gz"


def _build_assets(
    config: GeekbenchConfig,
    url: str,
    version: str,
    suffix: str,
) -> _GeekbenchAssets:
    archive_name = (
        Path(urlparse(url).path).name
        or f"Geekbench-{version}-{suffix}.tar.gz"
    )
    archive_path = config.workdir / archive_name
    stem = archive_name[:-7] if archive_name.endswith(".tar.gz") else archive_name
    extract_dir = config.workdir / stem
    executable = extract_dir / "geekbench6"
    if config.run_gpu:
        executable = extract_dir / "geekbench6_compute"
    export_supported = "preview" not in archive_name.lower()
    return _GeekbenchAssets(
        executable=executable,
        archive_path=archive_path,
        extract_dir=extract_dir,
        archive_name=archive_name,
        export_supported=export_supported,
    )


def _download_archive(
    url: str,
    suffix: str,
    *,
    explicit_url: bool,
) -> Path:
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)
    dl_cmd = [
        "curl",
        "-fL",
        "--retry",
        "3",
        "--retry-delay",
        "1",
        "-sS",
        "-o",
        str(tmp_path),
        url,
    ]
    completed = subprocess.run(dl_cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        msg = completed.stderr or completed.stdout or "download failed"
        if "404" in msg and suffix == "LinuxARM64" and not explicit_url:
            raise RuntimeError(
                "Geekbench Linux ARM64 binary not available (404). "
                "Specify a valid download_url or run under an amd64 container/host."
            )
        raise RuntimeError(f"Failed to download Geekbench: {msg}")
    return tmp_path


def _validate_checksum(
    tmp_path: Path,
    *,
    checksum: str | None,
    archive_name: str,
) -> None:
    if not checksum:
        return
    try:
        import hashlib

        digest = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        if digest.lower() != checksum.lower():
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"Geekbench checksum mismatch for {archive_name}: expected "
                f"{checksum}, got {digest}"
            )
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Geekbench checksum validation failed: {exc}") from exc


def _validate_gzip_magic(tmp_path: Path, url: str) -> None:
    try:
        with tmp_path.open("rb") as fh:
            magic = fh.read(2)
        if magic != b"\x1f\x8b":
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Downloaded file is not a gzip archive from {url}")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _is_safe_path(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _extract_archive(archive_path: Path, workdir: Path) -> None:
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getmembers():
                member_path = workdir / member.name
                if not _is_safe_path(workdir, member_path):
                    raise RuntimeError(
                        f"Unsafe path in archive: {member.name}"
                    )
                tar.extract(member, workdir, filter="data")
    except Exception as exc:
        archive_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to extract Geekbench archive: {exc}") from exc


def _load_geekbench_payload(json_path: Path) -> dict[str, Any] | None:
    try:
        import pandas as pd

        return pd.read_json(json_path, typ="series").to_dict()  # type: ignore[arg-type]
    except Exception:
        try:
            return json.loads(json_path.read_text())
        except Exception:
            return None


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


def _iter_key_values(node: Any) -> Iterable[tuple[Any, Any]]:
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                yield key, value
                stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)


def _find_first_value(node: Any, keys: set[str]) -> Any:
    for key, value in _iter_key_values(node):
        nk = _normalize_key(str(key))
        if nk in keys:
            return value
    return None


def _find_first_score(node: Any, keys: set[str]) -> Optional[float]:
    for key, value in _iter_key_values(node):
        nk = _normalize_key(str(key))
        if nk in keys:
            num = _coerce_number(value)
            if num is not None:
                return num
    return None


def _collect_subtests(node: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for current in _iter_nodes(node):
        if isinstance(current, list) and all(isinstance(i, dict) for i in current):
            rows.extend(_collect_subtest_rows(current))
    return rows


def _iter_nodes(node: Any) -> Iterable[Any]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _collect_subtest_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        name = _subtest_name(item)
        score = item.get("score") or item.get("result") or item.get("value")
        num = _coerce_number(score)
        if name and num is not None:
            rows.append({"subtest": str(name), "score": num})
    return rows


def _subtest_name(item: dict[str, Any]) -> Any:
    return item.get("name") or item.get("benchmark_name") or item.get("workload")


def _resolve_json_path(gen_result: dict[str, Any], output_dir: Path) -> Optional[Path]:
    raw_json = gen_result.get("json_result")
    if isinstance(raw_json, str):
        candidate = Path(raw_json)
        if candidate.exists():
            return candidate
        local_candidate = output_dir / candidate.name
        if local_candidate.exists():
            return local_candidate

    candidates = list(output_dir.glob("geekbench*.json")) + list(
        output_dir.glob("*geekbench*.json")
    )
    return candidates[0] if candidates else None


_SINGLE_SCORE_KEYS = {
    "single_core_score",
    "single_core",
    "single_score",
    "single",
    "cpu_single_core_score",
    "singlecore_score",
}
_MULTI_SCORE_KEYS = {
    "multi_core_score",
    "multi_core",
    "multi_score",
    "multi",
    "cpu_multi_core_score",
    "multicore_score",
}
_VERSION_KEYS = {"geekbench_version", "version"}


class GeekbenchResultParser:
    """Parse Geekbench JSON exports into summary rows."""

    def __init__(self, output_dir: Path, default_version: str) -> None:
        self._output_dir = output_dir
        self._default_version = default_version

    def collect_rows(
        self,
        results: List[Dict[str, Any]],
        run_id: str,
        test_name: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return _collect_geekbench_rows(
            results,
            self._output_dir,
            run_id,
            test_name,
            self._default_version,
        )


def _collect_geekbench_rows(
    results: List[Dict[str, Any]],
    output_dir: Path,
    run_id: str,
    test_name: str,
    default_version: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summary_rows: list[dict[str, Any]] = []
    subtest_rows: list[dict[str, Any]] = []

    for entry in results:
        rep = entry.get("repetition")
        gen_result = entry.get("generator_result") or {}
        payload = _load_entry_payload(gen_result, output_dir)
        summary_rows.append(
            _build_summary_row(
                entry,
                gen_result,
                run_id,
                test_name,
                rep,
                payload,
                default_version,
            )
        )
        if payload:
            subtest_rows.extend(
                _build_subtest_rows(payload, run_id, test_name, rep)
            )

    return summary_rows, subtest_rows


def _load_entry_payload(
    gen_result: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any] | None:
    json_path = _resolve_json_path(gen_result, output_dir)
    return _load_geekbench_payload(json_path) if json_path else None


def _build_summary_row(
    entry: Dict[str, Any],
    gen_result: dict[str, Any],
    run_id: str,
    test_name: str,
    rep: Any,
    payload: dict[str, Any] | None,
    default_version: str,
) -> dict[str, Any]:
    single_score = _find_first_score(payload, _SINGLE_SCORE_KEYS) if payload else None
    multi_score = _find_first_score(payload, _MULTI_SCORE_KEYS) if payload else None
    gb_version = _resolve_geekbench_version(payload, gen_result, default_version)

    return {
        "run_id": run_id,
        "workload": test_name,
        "repetition": rep,
        "returncode": gen_result.get("returncode"),
        "success": entry.get("success"),
        "duration_seconds": entry.get("duration_seconds"),
        "single_core_score": single_score,
        "multi_core_score": multi_score,
        "geekbench_version": gb_version,
        "export_json_supported": gen_result.get("export_json_supported", True),
    }


def _resolve_geekbench_version(
    payload: dict[str, Any] | None,
    gen_result: dict[str, Any],
    default_version: str,
) -> str:
    gb_version_raw = _find_first_value(payload, _VERSION_KEYS) if payload else None
    if gb_version_raw is not None and gb_version_raw != "":
        return str(gb_version_raw)
    return str(gen_result.get("version") or default_version)


def _build_subtest_rows(
    payload: dict[str, Any],
    run_id: str,
    test_name: str,
    rep: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _collect_subtests(payload):
        rows.append(
            {
                "run_id": run_id,
                "workload": test_name,
                "repetition": rep,
                **row,
            }
        )
    return rows


class _GeekbenchCommandBuilder:
    def __init__(self, generator: "GeekbenchGenerator"):
        self._generator = generator

    def build(self, config: GeekbenchConfig) -> CommandSpec:
        executable = self._generator._executable
        if not executable:
            raise RuntimeError("Geekbench executable not prepared")

        cmd: List[str] = [str(executable)]
        if config.license_key:
            cmd.extend(["--unlock", config.license_key])
        if config.run_gpu:
            cmd.append("--compute")
        if self._generator._use_export_flag and self._generator._export_path:
            cmd.extend(["--export-json", str(self._generator._export_path)])
        else:
            cmd.append("--cpu")
        if config.extra_args:
            cmd.extend(config.extra_args)
        return CommandSpec(cmd=cmd)


class GeekbenchGenerator(CommandGenerator):
    """Generator that runs Geekbench CPU benchmark."""

    def __init__(self, config: GeekbenchConfig):
        self._command_builder = _GeekbenchCommandBuilder(self)
        super().__init__(
            "GeekbenchGenerator",
            config,
            command_builder=self._command_builder,
        )
        self._download_ready: bool = False
        self._download_error: Optional[str] = None
        self._export_supported: bool = True
        self._executable: Optional[Path] = None
        self._current_env: dict[str, str] = {}
        self._current_cwd: Optional[Path] = None
        self._export_path: Optional[Path] = None
        self._log_path: Optional[Path] = None
        self._use_export_flag: bool = False
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

    def _build_command(self) -> list[str]:
        return self._command_builder.build(self.config).cmd

    def _popen_kwargs(self) -> dict[str, Any]:
        return {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "cwd": self._current_cwd,
            "env": self._current_env,
        }

    def _timeout_seconds(self) -> Optional[int]:
        return self.expected_runtime_seconds

    def _log_command(self, cmd: list[str]) -> None:
        if self.config.debug:
            logger.info("Running Geekbench command: %s", " ".join(cmd))

    def _after_run(
        self,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> None:
        self._record_log(stdout, stderr)
        self._record_export()

    def _record_log(self, stdout: str, stderr: str) -> None:
        if not self._log_path:
            return
        try:
            self._log_path.write_text((stdout or "") + "\n" + (stderr or ""))
        except Exception:  # pragma: no cover - best effort
            return
        if isinstance(self._result, dict):
            self._result["log_path"] = str(self._log_path)

    def _record_export(self) -> None:
        if not isinstance(self._result, dict):
            return
        if self._use_export_flag and self._export_supported and self._export_path:
            if self._export_path.exists():
                self._result["json_result"] = str(self._export_path)
            return
        self._result["export_json_supported"] = False

    def _run_command(self) -> None:
        """Download and execute Geekbench."""
        if not self._validate_environment():
            self._result = {"error": "Environment validation failed"}
            self._is_running = False
            return

        archive_path, extract_dir = self._execute_with_handling()
        self._cleanup_execution(archive_path, extract_dir)
        self._is_running = False

    def _execute_with_handling(self) -> tuple[Path | None, Path | None]:
        archive_path: Path | None = None
        extract_dir: Path | None = None
        try:
            archive_path, extract_dir = self._prepare_execution_context()
            self._run_with_export_fallback()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Geekbench execution error: %s", exc)
            self._result = {"error": str(exc)}
            self._download_error = str(exc)
        return archive_path, extract_dir

    def _cleanup_execution(
        self, archive_path: Path | None, extract_dir: Path | None
    ) -> None:
        if self.config.skip_cleanup:
            return
        self._safe_rmtree(extract_dir)
        self._safe_unlink(archive_path)

    @staticmethod
    def _safe_rmtree(path: Path | None) -> None:
        if not path:
            return
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:  # pragma: no cover - best effort
            pass

    @staticmethod
    def _safe_unlink(path: Path | None) -> None:
        if not path:
            return
        path.unlink(missing_ok=True)

    def _prepare_execution_context(self) -> tuple[Path, Path]:
        executable, archive_path, extract_dir = self._prepare_geekbench()
        self._executable = executable
        self._current_cwd = executable.parent
        self._current_env = os.environ.copy()
        self._export_path = self._build_export_path()
        self._log_path = self.config.output_dir / "geekbench.log"
        return archive_path, extract_dir

    def _build_export_path(self) -> Path:
        return self.config.output_dir / f"geekbench_result_{time.time_ns()}.json"

    def _run_with_export_fallback(self) -> None:
        self._use_export_flag = self._export_supported
        self._run_once()
        retry, original_rc = self._should_retry_without_export()
        if not retry:
            return
        self._use_export_flag = False
        self._run_once()
        if isinstance(self._result, dict):
            self._result["export_json_supported"] = False
            if original_rc is not None:
                self._result["original_returncode"] = original_rc

    def _run_once(self) -> None:
        super()._run_command()

    def _should_retry_without_export(self) -> tuple[bool, Optional[int]]:
        if not self._use_export_flag:
            return False, None
        first_result = self._result if isinstance(self._result, dict) else {}
        export_failed = bool(
            self._export_path and not self._export_path.exists()
        )
        stderr_value = first_result.get("stderr") or ""
        stderr_lower = stderr_value.lower() if isinstance(stderr_value, str) else ""
        export_flag_error = any(
            token in stderr_lower
            for token in (
                "export-json",
                "unknown option",
                "unrecognized option",
                "invalid option",
            )
        )
        should_retry = (
            first_result.get("returncode") != 0 or export_failed or export_flag_error
        )
        return should_retry, first_result.get("returncode")

    def _prepare_geekbench(self) -> Tuple[Path, Path, Path]:
        """Ensure Geekbench is downloaded and extracted; return asset paths."""
        if self._download_error:
            raise RuntimeError(self._download_error)

        version = self.config.version
        url_hint = self.config.download_url or _default_download_url(version)
        suffix = _resolve_arch_suffix(self.config, url_hint)
        url = _resolve_download_url(self.config, version, suffix)

        assets = _build_assets(self.config, url, version, suffix)
        self._export_supported = assets.export_supported

        if assets.executable.exists():
            self._download_ready = True
            return assets.executable, assets.archive_path, assets.extract_dir

        tmp_path = _download_archive(
            url,
            suffix,
            explicit_url=bool(self.config.download_url),
        )
        _validate_checksum(
            tmp_path,
            checksum=self.config.download_checksum,
            archive_name=assets.archive_name,
        )
        _validate_gzip_magic(tmp_path, url)

        assets.archive_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_path), assets.archive_path)
        _extract_archive(assets.archive_path, self.config.workdir)

        if not assets.executable.exists():
            raise RuntimeError(
                f"Geekbench executable not found at {assets.executable}"
            )

        assets.executable.chmod(0o755)
        self._download_ready = True
        return assets.executable, assets.archive_path, assets.extract_dir

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


class GeekbenchPlugin(SimpleWorkloadPlugin):
    """Plugin wrapper for Geekbench."""

    NAME = "geekbench"
    DESCRIPTION = "Geekbench 6 CPU benchmark"
    CONFIG_CLS = GeekbenchConfig
    GENERATOR_CLS = GeekbenchGenerator
    REQUIRED_APT_PACKAGES = ["curl", "wget", "tar", "ca-certificates", "sysstat"]
    REQUIRED_LOCAL_TOOLS = ["curl", "wget", "tar"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[GeekbenchConfig]:
        if level == WorkloadIntensity.LOW:
            return GeekbenchConfig(skip_cleanup=True, run_gpu=False)
        if level == WorkloadIntensity.MEDIUM:
            return GeekbenchConfig(skip_cleanup=True, run_gpu=False)
        if level == WorkloadIntensity.HIGH:
            return GeekbenchConfig(skip_cleanup=False, run_gpu=False)
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
        output_dir.mkdir(parents=True, exist_ok=True)
        parser = GeekbenchResultParser(output_dir, self.config_cls().version)
        summary_rows, subtest_rows = parser.collect_rows(
            results,
            run_id,
            test_name,
        )
        if not summary_rows:
            return []

        csv_paths: list[Path] = []
        summary_path = output_dir / f"{test_name}_plugin.csv"
        write_csv_rows(
            summary_rows,
            summary_path,
            [
                "run_id",
                "workload",
                "repetition",
                "returncode",
                "success",
                "duration_seconds",
                "single_core_score",
                "multi_core_score",
                "geekbench_version",
                "export_json_supported",
            ],
        )
        csv_paths.append(summary_path)

        if subtest_rows:
            sub_path = output_dir / f"{test_name}_subtests.csv"
            write_csv_rows(
                subtest_rows,
                sub_path,
                ["run_id", "workload", "repetition", "subtest", "score"],
            )
            csv_paths.append(sub_path)

        return csv_paths


PLUGIN = GeekbenchPlugin()
