"""
YABS (Yet Another Benchmark Script) workload plugin.

This plugin downloads and executes the upstream yabs.sh script to run
combined CPU/disk/network benchmarks. It avoids Geekbench by default to
reduce external dependencies/licensing friction.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, List, Optional

from pydantic import Field

from ...interface import SimpleWorkloadPlugin, WorkloadIntensity, BasePluginConfig
from ...base_generator import CommandGenerator, CommandSpec

logger = logging.getLogger(__name__)

YABS_URL = (
    "https://raw.githubusercontent.com/masonr/yet-another-bench-script/master/yabs.sh"
)


def _default_yabs_output_dir() -> Path:
    return Path(tempfile.gettempdir()) / "lb_yabs"


class YabsConfig(BasePluginConfig):
    """Configuration for the YABS workload."""

    script_url: str = Field(default=YABS_URL, description="URL to the YABS script")
    script_checksum: Optional[str] = Field(
        default=None, description="SHA256 checksum for script validation"
    )
    skip_disk: bool = Field(default=False, description="Skip disk benchmarks (fio)")
    skip_network: bool = Field(
        default=False, description="Skip network benchmarks (iperf)"
    )
    skip_geekbench: bool = Field(default=True, description="Skip Geekbench benchmark")
    skip_cleanup: bool = Field(default=True, description="Skip temporary file cleanup")
    output_dir: Path = Field(
        default_factory=_default_yabs_output_dir,
        description="Directory for YABS log files",
    )
    extra_args: List[str] = Field(
        default_factory=list, description="Additional arguments to pass to yabs.sh"
    )
    expected_runtime_seconds: int = Field(
        default=600,
        gt=0,
        description="Expected runtime of YABS in seconds (used for timeout hints)",
    )
    debug: bool = Field(default=False, description="Enable debug logging")

    # Removed __post_init__ as Pydantic handles Path conversion


class _YabsCommandBuilder:
    def __init__(self, script_path: Path):
        self._script_path = script_path

    def build(
        self, config: YabsConfig, include_skip_cleanup: bool = True
    ) -> CommandSpec:
        args: list[str] = [str(self._script_path)]
        if config.skip_disk:
            args.append("-f")  # skip fio
        if config.skip_network:
            args.append("-i")  # skip iperf
        if config.skip_geekbench:
            args.append("-g")  # skip geekbench
        if include_skip_cleanup and config.skip_cleanup:
            args.append("-c")  # skip cleanup (not supported by all upstream revisions)
        if config.extra_args:
            args.extend(config.extra_args)
        return CommandSpec(cmd=args)


class YabsGenerator(CommandGenerator):
    """Generator that runs the upstream yabs.sh script."""

    def __init__(self, config: YabsConfig):
        super().__init__("YabsGenerator", config)
        self._current_args: list[str] = []
        self._env: dict[str, str] = {}
        self._log_path: Optional[Path] = None
        self._command_builder: _YabsCommandBuilder | None = None
        self._include_skip_cleanup = True
        # expected_runtime_seconds comes directly from config.

    def _validate_environment(self) -> bool:
        """Ensure required tools are present and output dir is writable."""
        for tool in ("curl", "wget", "bash"):
            if shutil.which(tool) is None:
                logger.error("Required tool missing: %s", tool)
                return False
        try:
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error(
                "Failed to create output_dir %s: %s", self.config.output_dir, exc
            )
            return False
        if not os.access(self.config.output_dir, os.W_OK):
            logger.error("Output dir not writable: %s", self.config.output_dir)
            return False
        return True

    def _build_command(self) -> list[str]:
        if self._command_builder is None:
            return list(self._current_args)
        return self._command_builder.build(
            self.config, include_skip_cleanup=self._include_skip_cleanup
        ).cmd

    def _popen_kwargs(self) -> dict[str, Any]:
        return {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "env": self._env,
        }

    def _build_command_spec(self) -> CommandSpec:
        if self._command_builder is None:
            return super()._build_command_spec()
        spec = self._command_builder.build(
            self.config, include_skip_cleanup=self._include_skip_cleanup
        )
        if not spec.popen_kwargs:
            spec.popen_kwargs = self._popen_kwargs()
        if spec.timeout_seconds is None:
            spec.timeout_seconds = self._timeout_seconds()
        self._current_args = list(spec.cmd)
        return spec

    def _timeout_seconds(self) -> Optional[int]:
        return self.config.expected_runtime_seconds + self.config.timeout_buffer

    def _log_command(self, cmd: list[str]) -> None:
        if self.config.debug:
            logger.info("Running YABS command (configured): %s", " ".join(cmd))
        else:
            logger.info("Running YABS command: %s", " ".join(cmd))

    def _after_run(
        self,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> None:
        if not self._log_path:
            return
        try:
            self._log_path.write_text((stdout or "") + "\n" + (stderr or ""))
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Failed to write yabs log: %s", exc)
        self._result["log_path"] = str(self._log_path)

    def _should_retry_without_cleanup(self) -> bool:
        if not self._can_retry_cleanup():
            return False
        combined = self._combined_output()
        if not combined:
            return False
        return self._has_cleanup_error(combined)

    def _can_retry_cleanup(self) -> bool:
        if not self.config.skip_cleanup:
            return False
        if "-c" not in self._current_args:
            return False
        if not isinstance(self._result, dict):
            return False
        return self._result.get("returncode") not in (None, 0)

    def _combined_output(self) -> str | None:
        if not isinstance(self._result, dict):
            return None
        stderr = self._result.get("stderr") or ""
        stdout = self._result.get("stdout") or ""
        if not isinstance(stderr, str) or not isinstance(stdout, str):
            return None
        return f"{stdout}\n{stderr}".lower()

    @staticmethod
    def _has_cleanup_error(output: str) -> bool:
        tokens = (
            "illegal option",
            "unknown option",
            "unrecognized option",
            "invalid option",
        )
        return any(token in output for token in tokens)

    def _run_command(self) -> None:
        """Download and execute yabs.sh with configured flags."""
        if not self._validate_environment():
            self._result = {"error": "Environment validation failed"}
            self._is_running = False
            return

        script_path: Optional[Path] = None
        try:
            script_path = self._download_script()
            self._prepare_execution(script_path)
            self._execute_with_retry()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("YABS execution error: %s", exc)
            self._result = {"error": str(exc), "returncode": -2}
        finally:
            self._cleanup_script(script_path)
            self._is_running = False

    def _download_script(self) -> Path:
        # Download script to a temp location
        fd, path_str = tempfile.mkstemp(prefix="yabs-", suffix=".sh")
        os.close(fd)
        script_path = Path(path_str)
        dl_cmd = ["curl", "-sLo", str(script_path), self.config.script_url]
        self._run_checked(dl_cmd, "Failed to download yabs.sh")
        if self.config.script_checksum:
            import hashlib

            digest = hashlib.sha256(script_path.read_bytes()).hexdigest()
            if digest.lower() != self.config.script_checksum.lower():
                raise RuntimeError(
                    "YABS script checksum mismatch: expected "
                    f"{self.config.script_checksum}, got {digest}"
                )
        script_path.chmod(0o755)
        return script_path

    def _prepare_execution(self, script_path: Path) -> None:
        self._env = os.environ.copy()
        # Prevent interactive prompts
        self._env.setdefault("YABS_NONINTERACTIVE", "1")
        self._log_path = self.config.output_dir / "yabs.log"
        self._command_builder = _YabsCommandBuilder(script_path)
        self._include_skip_cleanup = True

    def _execute_with_retry(self) -> None:
        super()._run_command()
        if self._should_retry_without_cleanup():
            logger.info(
                "YABS script does not support -c; retrying without skip_cleanup flag"
            )
            self._include_skip_cleanup = False
            super()._run_command()

    @staticmethod
    def _cleanup_script(script_path: Optional[Path]) -> None:
        if script_path and script_path.exists():
            try:
                script_path.unlink()
            except Exception:
                pass

    def _run_checked(self, cmd: List[str], error_message: str) -> None:
        """Run a command and raise on failure."""
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(
                f"{error_message}: rc={completed.returncode}, stderr={completed.stderr}"
            )


class YabsPlugin(SimpleWorkloadPlugin):
    """Plugin wrapper for YABS."""

    NAME = "yabs"
    DESCRIPTION = "Yet Another Bench Script (CPU/disk/network)"
    CONFIG_CLS = YabsConfig
    GENERATOR_CLS = YabsGenerator
    REQUIRED_APT_PACKAGES = ["curl", "wget", "fio", "iperf3", "bc", "tar"]
    REQUIRED_LOCAL_TOOLS = ["bash", "curl", "wget"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[YabsConfig]:
        # Intensities map to which portions we run; Geekbench remains skipped.
        # Durations: curl/wget+iperf+fio add seconds; cleanup skipped on low levels.
        if level == WorkloadIntensity.LOW:
            # Quick check: network only, skip disk to keep runtime short.
            return YabsConfig(
                skip_disk=True,
                skip_network=False,
                skip_geekbench=True,
                skip_cleanup=True,
            )
        if level == WorkloadIntensity.MEDIUM:
            # Network + disk, skip cleanup for speed.
            return YabsConfig(
                skip_disk=False,
                skip_network=False,
                skip_geekbench=True,
                skip_cleanup=True,
            )
        if level == WorkloadIntensity.HIGH:
            # Full run, include cleanup to leave system tidy.
            return YabsConfig(
                skip_disk=False,
                skip_network=False,
                skip_geekbench=True,
                skip_cleanup=False,
            )
        return None

    def export_results_to_csv(
        self,
        results: List[dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> List[Path]:
        """Export YABS summary metrics parsed from stdout to CSV."""
        import pandas as pd

        rows: list[dict[str, Any]] = []
        for entry in results:
            gen_result = entry.get("generator_result") or {}
            stdout = gen_result.get("stdout") or ""
            if not isinstance(stdout, str):
                stdout = ""
            rows.append(
                self._build_export_row(
                    entry,
                    gen_result,
                    stdout,
                    run_id,
                    test_name,
                )
            )

        if not rows:
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{test_name}_plugin.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        return [csv_path]

    def _build_export_row(
        self,
        entry: dict[str, Any],
        gen_result: dict[str, Any],
        stdout: str,
        run_id: str,
        test_name: str,
    ) -> dict[str, Any]:
        import re

        return {
            "run_id": run_id,
            "workload": test_name,
            "repetition": entry.get("repetition"),
            "returncode": gen_result.get("returncode"),
            "success": entry.get("success"),
            "duration_seconds": entry.get("duration_seconds"),
            "cpu_events_per_sec": self._last_float(
                r"Events per second:\s*([0-9.]+)", stdout
            ),
            "cpu_total_time_sec": self._last_float(
                r"total time:\s*([0-9.]+)\s*s", stdout, flags=re.IGNORECASE
            ),
            "disk_read_mb_s": self._last_float(
                r"Read:\s*([0-9.]+)\s*MB/s", stdout, flags=re.IGNORECASE
            ),
            "disk_write_mb_s": self._last_float(
                r"Write:\s*([0-9.]+)\s*MB/s", stdout, flags=re.IGNORECASE
            ),
            "net_download_mbits": self._last_float(
                r"Download:\s*([0-9.]+)\s*Mbits/sec",
                stdout,
                flags=re.IGNORECASE,
            ),
            "net_upload_mbits": self._last_float(
                r"Upload:\s*([0-9.]+)\s*Mbits/sec",
                stdout,
                flags=re.IGNORECASE,
            ),
            "cpu_model": self._last_str(r"CPU Model:\s*(.+)", stdout),
            "arch": self._last_str(r"Architecture:\s*(.+)", stdout),
            "virt": self._last_str(r"Virtualization:\s*(.+)", stdout),
            "max_retries": gen_result.get("max_retries"),
            "tags": gen_result.get("tags"),
        }

    @staticmethod
    def _last_float(pattern: str, text: str, flags: int = 0) -> Optional[float]:
        import re

        matches = re.findall(pattern, text, flags=flags)
        if not matches:
            return None
        try:
            return float(matches[-1])
        except Exception:
            return None

    @staticmethod
    def _last_str(pattern: str, text: str) -> Optional[str]:
        import re

        matches = re.findall(pattern, text)
        if not matches:
            return None
        val = matches[-1]
        return val.strip() if isinstance(val, str) else str(val).strip()


PLUGIN = YabsPlugin()
