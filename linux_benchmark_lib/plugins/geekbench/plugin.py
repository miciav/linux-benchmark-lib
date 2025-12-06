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
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from typing import List, Optional, Type, Any, Tuple

from ...plugin_system.interface import WorkloadPlugin, WorkloadIntensity
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


@dataclass
class GeekbenchConfig:
    """Configuration for Geekbench."""

    version: str = "6.3.0"
    download_url: Optional[str] = None
    workdir: Path = Path("/opt/geekbench")
    output_dir: Path = Path("/tmp")
    license_key: Optional[str] = None
    skip_cleanup: bool = True
    run_gpu: bool = False
    extra_args: List[str] = field(default_factory=list)
    arch_override: Optional[str] = None
    debug: bool = False


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
        self.expected_runtime_seconds = int(os.environ.get("LB_GEEKBENCH_TIMEOUT", "1800"))

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
            export_path = self.config.output_dir / "geekbench_result.json"

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

            # Fallback: if export-json is unsupported (Pro-only) retry without it
            if run.returncode != 0 and self._export_supported and "export-json" in (run.stderr or "").lower():
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
                url = "https://cdn.geekbench.com/Geekbench-6.5.0-LinuxARMPreview.tar.gz"
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


PLUGIN = GeekbenchPlugin()
