"""YABS (Yet Another Benchmark Script) workload plugin.

This plugin downloads and executes the upstream yabs.sh script to run
combined CPU/disk/network benchmarks. It avoids Geekbench by default to
reduce external dependencies/licensing friction.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from pydantic import Field

from lb_common.api import DatasetDescriptor, MetricSpec, ValueColumn
from lb_plugins.base_generator import CommandGenerator, CommandSpec
from lb_plugins.datasets import plugin_csv_dataset
from lb_plugins.interface import (
    BasePluginConfig,
    SimpleWorkloadPlugin,
    WorkloadIntensity,
)

logger = logging.getLogger(__name__)

YABS_URL = (
    "https://raw.githubusercontent.com/masonr/yet-another-bench-script/master/yabs.sh"
)


def _default_yabs_output_dir() -> Path:
    return Path(tempfile.gettempdir()) / "lb_yabs"


class YabsConfig(BasePluginConfig):
    """Configuration for the YABS workload."""

    script_url: str = Field(default=YABS_URL, description="URL to the YABS script")
    script_checksum: str | None = Field(
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
    extra_args: list[str] = Field(
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
        # -j prints the whole result as one JSON line at the end of stdout.
        args: list[str] = [str(self._script_path), "-j"]
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
        self.config: YabsConfig = config
        self._result: dict[str, Any] | None = None
        self._current_args: list[str] = []
        self._env: dict[str, str] = {}
        self._log_path: Path | None = None
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

    def _timeout_seconds(self) -> int | None:
        return int(self.config.expected_runtime_seconds) + int(
            self.config.timeout_buffer
        )

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
        if self._result is None:
            self._result = {}
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
            startup_failure: dict[str, Any] = {"error": "Environment validation failed"}
            self._result = startup_failure
            self._is_running = False
            return

        script_path: Path | None = None
        try:
            script_path = self._download_script()
            self._prepare_execution(script_path)
            self._execute_with_retry()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("YABS execution error: %s", exc)
            exec_failure: dict[str, Any] = {"error": str(exc), "returncode": -2}
            self._result = exec_failure
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
    def _cleanup_script(script_path: Path | None) -> None:
        if script_path and script_path.exists():
            with contextlib.suppress(Exception):
                script_path.unlink()

    def _run_checked(self, cmd: list[str], error_message: str) -> None:
        """Run a command and raise on failure."""
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(
                f"{error_message}: rc={completed.returncode}, stderr={completed.stderr}"
            )


_BLOCK = r"^fio_(?P<block_size>[^_]+)_"


class YabsPlugin(SimpleWorkloadPlugin):
    """Plugin wrapper for YABS."""

    NAME = "yabs"
    DESCRIPTION = "Yet Another Bench Script (CPU/disk/network)"
    CONFIG_CLS = YabsConfig
    GENERATOR_CLS = YabsGenerator
    REQUIRED_APT_PACKAGES: ClassVar[list[str]] = [
        "curl",
        "wget",
        "fio",
        "iperf3",
        "bc",
        "tar",
    ]
    REQUIRED_LOCAL_TOOLS: ClassVar[list[str]] = ["bash", "curl", "wget"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"

    def describe_datasets(
        self, output_dir: Path, test_name: str
    ) -> list[DatasetDescriptor]:
        plugin_csv = output_dir / f"{test_name}_plugin.csv"
        header = ""
        if plugin_csv.exists():
            with plugin_csv.open() as handle:
                header = handle.readline()
        # Each yabs section can be skipped (skip_disk, skip_geekbench): declare
        # only the families the run produced, so every pattern matches a column.
        metrics: list[MetricSpec] = []
        if "fio_" in header:
            metrics += [
                MetricSpec(
                    pattern=_BLOCK + r"(?P<metric>speed_(?:r|w|rw))$", unit="KB/s"
                ),
                MetricSpec(
                    pattern=_BLOCK + r"(?P<metric>iops_(?:r|w|rw))$", unit="IOPS"
                ),
            ]
        if "geekbench" in header:
            metrics.append(
                MetricSpec(
                    pattern=r"^geekbench(?P<geekbench_version>\d+)_"
                    r"(?P<metric>single|multi)$",
                    unit="points",
                )
            )
        datasets = [
            plugin_csv_dataset(
                test_name,
                metrics=metrics,
                # Host facts duplicated from system_info, which owns them.
                exclude=["cpu_cores", "ram_kib", "swap_kib", "disk_kb", "cpu_aes"],
            )
        ]
        if (output_dir / f"{test_name}_iperf.csv").exists():
            datasets.append(
                DatasetDescriptor(
                    name=f"{test_name}_iperf",
                    path=f"{test_name}_iperf.csv",
                    shape="long",
                    keys=["mode", "provider", "location"],
                    value_columns=[
                        ValueColumn(column="send_mbits", unit="Mbit/s"),
                        ValueColumn(column="recv_mbits", unit="Mbit/s"),
                        ValueColumn(column="latency_ms", unit="ms"),
                    ],
                )
            )
        return datasets

    def get_preset_config(self, level: WorkloadIntensity) -> YabsConfig | None:
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
        results: list[dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> list[Path]:
        """Export the JSON summary YABS prints with -j.

        One summary row per repetition (system, fio per block size, Geekbench)
        and one iperf row per repetition, direction and server.
        """
        import pandas as pd

        rows: list[dict[str, Any]] = []
        iperf_rows: list[dict[str, Any]] = []
        for entry in results:
            gen_result = entry.get("generator_result") or {}
            payload = _yabs_json(gen_result.get("stdout"))
            base = {
                "run_id": run_id,
                "workload": test_name,
                "repetition": entry.get("repetition"),
            }
            rows.append(
                {
                    **base,
                    "returncode": gen_result.get("returncode"),
                    "success": entry.get("success"),
                    "duration_seconds": entry.get("duration_seconds"),
                    **_yabs_summary(payload),
                }
            )
            iperf_rows.extend({**base, **row} for row in _yabs_iperf(payload))

        if not rows:
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{test_name}_plugin.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        paths = [csv_path]
        if iperf_rows:
            iperf_path = output_dir / f"{test_name}_iperf.csv"
            pd.DataFrame(iperf_rows).to_csv(iperf_path, index=False)
            paths.append(iperf_path)
        return paths


def _yabs_json(stdout: Any) -> dict[str, Any]:
    """Return the JSON summary printed by `yabs.sh -j`, or {} if absent.

    yabs builds it by string concatenation, so values can carry raw newlines
    (e.g. a multi-line CPU model on ARM): the blob may span several lines and
    needs strict=False.
    """
    if not isinstance(stdout, str):
        return {}
    start = stdout.rfind('{"version":')
    if start < 0:
        return {}
    try:
        payload = json.loads(stdout[start:].strip(), strict=False)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _yabs_summary(payload: dict[str, Any]) -> dict[str, Any]:
    os_info = payload.get("os") or {}
    cpu = payload.get("cpu") or {}
    mem = payload.get("mem") or {}
    row: dict[str, Any] = {
        "yabs_version": payload.get("version"),
        "arch": os_info.get("arch"),
        "distro": os_info.get("distro"),
        "kernel": os_info.get("kernel"),
        "virt": os_info.get("vm"),
        "cpu_model": cpu.get("model"),
        "cpu_cores": cpu.get("cores"),
        "cpu_freq": cpu.get("freq"),
        "cpu_aes": cpu.get("aes"),
        "ram_kib": mem.get("ram"),
        "swap_kib": mem.get("swap"),
        "disk_kb": mem.get("disk"),
    }
    # fio speeds are reported in KB/s.
    for fio in payload.get("fio") or []:
        bs = fio.get("bs")
        for key in ("speed_r", "speed_w", "speed_rw", "iops_r", "iops_w", "iops_rw"):
            row[f"fio_{bs}_{key}"] = fio.get(key)
    for geekbench in payload.get("geekbench") or []:
        version = geekbench.get("version")
        row[f"geekbench{version}_single"] = geekbench.get("single")
        row[f"geekbench{version}_multi"] = geekbench.get("multi")
    return row


_BITRATE_SCALE_TO_MBITS = {"Kbits/sec": 1e-3, "Mbits/sec": 1.0, "Gbits/sec": 1e3}


def _to_mbits(value: Any) -> float | None:
    """'931 Mbits/sec' -> 931.0; 'busy' or empty -> None."""
    parts = str(value or "").split()
    if len(parts) != 2 or parts[1] not in _BITRATE_SCALE_TO_MBITS:
        return None
    try:
        return float(parts[0]) * _BITRATE_SCALE_TO_MBITS[parts[1]]
    except ValueError:
        return None


def _to_ms(value: Any) -> float | None:
    parts = str(value or "").split()
    if len(parts) != 2 or parts[1] != "ms":
        return None
    try:
        return float(parts[0])
    except ValueError:
        return None


def _yabs_iperf(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "mode": item.get("mode"),
            "provider": item.get("provider"),
            "location": item.get("loc"),
            "send_mbits": _to_mbits(item.get("send")),
            "recv_mbits": _to_mbits(item.get("recv")),
            "latency_ms": _to_ms(item.get("latency")),
        }
        for item in payload.get("iperf") or []
    ]


PLUGIN = YabsPlugin()
