"""
FIO workload generator implementation.

This module uses fio (Flexible I/O Tester) to generate advanced disk I/O workloads.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field

from ...base_generator import CommandGenerator
from ...interface import WorkloadIntensity, SimpleWorkloadPlugin, BasePluginConfig


logger = logging.getLogger(__name__)

def _default_fio_directory() -> str:
    return tempfile.gettempdir()


class FIOConfig(BasePluginConfig):
    """Configuration for fio I/O testing."""

    job_file: Optional[Path] = Field(default=None, description="Path to a custom FIO job file")
    runtime: int = Field(default=60, gt=0, description="Duration of the test in seconds")
    rw: str = Field(default="randrw", description="Read/write pattern (e.g., randrw, read, write)")
    bs: str = Field(default="4k", description="Block size for I/O operations (e.g., 4k, 1M)")
    iodepth: int = Field(default=16, gt=0, description="Number of I/O units to keep in flight")
    numjobs: int = Field(default=1, gt=0, description="Number of jobs to run concurrently")
    size: str = Field(default="1G", description="Total size of the I/O for each job")
    directory: str = Field(
        default_factory=_default_fio_directory,
        description="Directory to store test files",
    )
    name: str = Field(default="benchmark", description="Name of the FIO job")
    output_format: str = Field(default="json", description="Output format (e.g., json, normal)")
    debug: bool = Field(default=False, description="Enable debug logging for fio")


class FIOGenerator(CommandGenerator):
    """Workload generator using fio."""
    
    def __init__(self, config: FIOConfig, name: str = "FIOGenerator"):
        """
        Initialize the fio generator.
        
        Args:
            config: Configuration for fio
            name: Name of the generator
        """
        super().__init__(name, config)
        self._debug_enabled = bool(config.debug)
        self._setup_debug_logging()

    def _setup_debug_logging(self) -> None:
        """Attach a stream handler when debug is enabled to surface fio logs."""
        if not self._debug_enabled:
            return

        logger.setLevel(logging.DEBUG)
        for handler in logger.handlers:
            if getattr(handler, "_lb_fio_debug", False):
                return

        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        handler._lb_fio_debug = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.debug("FIO debug logging enabled")
    
    def _build_command(self) -> List[str]:
        """
        Build the fio command from configuration.
        
        Returns:
            List of command arguments
        """
        cmd = ["fio"]
        
        # If a job file is provided, use it
        if self.config.job_file:
            logger.debug("Using job file for fio: %s", self.config.job_file)
            cmd.append(str(self.config.job_file))
        else:
            # Build command line arguments
            cmd.extend([
                f"--name={self.config.name}",
                f"--rw={self.config.rw}",
                f"--bs={self.config.bs}",
                f"--runtime={self.config.runtime}",
                f"--iodepth={self.config.iodepth}",
                f"--numjobs={self.config.numjobs}",
                f"--size={self.config.size}",
                f"--directory={self.config.directory}",
                "--time_based",
                "--group_reporting",
                f"--output-format={self.config.output_format}"
            ])

        logger.debug("Built fio command with config: %s", self.config.model_dump_json()) # Using model_dump_json for Pydantic config
        
        return cmd

    def _log_command(self, cmd: list[str]) -> None:
        logger.info("Running command: %s", " ".join(cmd))
        logger.debug("Working directory: %s", self.config.directory)
    
    def _validate_environment(self) -> bool:
        """
        Validate that fio is available.
        
        Returns:
            True if fio is available, False otherwise
        """
        try:
            result = subprocess.run(
                ["which", "fio"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Error checking for fio: {e}")
            return False

    def _timeout_seconds(self) -> Optional[int]:
        return self.config.runtime + self.config.timeout_buffer
    
    def _parse_json_output(self, output: str) -> dict:
        """
        Parse fio JSON output.
        
        Args:
            output: Raw JSON output from fio
            
        Returns:
            Parsed results dictionary
        """
        if not output or not output.strip():
            logger.error("fio produced no output to parse")
            return {}

        decoder = json.JSONDecoder()
        parsed_data: Optional[dict[str, Any]] = None

        # fio may prepend warnings or termination notices before the JSON payload.
        for idx, char in enumerate(output):
            if char not in "{[":
                continue
            try:
                candidate, _ = decoder.raw_decode(output[idx:])
                if isinstance(candidate, dict):
                    parsed_data = candidate
                    logger.debug("Found fio JSON payload at offset %d", idx)
                    break
            except json.JSONDecodeError:
                continue

        if not parsed_data:
            snippet = output[:200].replace("\n", "\\n")
            logger.error(
                "Failed to locate fio JSON payload. Output starts with: %s", snippet
            )
            return {}

        jobs = parsed_data.get("jobs")
        if not jobs:
            logger.error("fio JSON payload missing 'jobs' section")
            return {}

        job = jobs[0]
        return {
            "read_iops": job.get("read", {}).get("iops", 0),
            "read_bw_mb": job.get("read", {}).get("bw", 0) / 1024,
            "read_lat_ms": job.get("read", {}).get("lat_ns", {}).get("mean", 0) / 1e6,
            "write_iops": job.get("write", {}).get("iops", 0),
            "write_bw_mb": job.get("write", {}).get("bw", 0) / 1024,
            "write_lat_ms": job.get("write", {}).get("lat_ns", {}).get("mean", 0)
            / 1e6,
        }

    def _build_result(
        self, cmd: list[str], stdout: str, stderr: str, returncode: int | None
    ) -> dict[str, Any]:
        parsed_result: dict[str, Any] = {}
        if self.config.output_format == "json":
            logger.debug("Parsing fio JSON output")
            parsed_result = self._parse_json_output(stdout)
            logger.debug("Parsed fio JSON metrics: %s", parsed_result)

        result = super()._build_result(cmd, stdout, stderr, returncode)
        result["parsed"] = parsed_result
        return result

    def _after_run(
        self,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> None:
        logger.debug(
            "fio finished with rc=%s (stdout=%d chars, stderr=%d chars)",
            returncode,
            len(stdout or ""),
            len(stderr or ""),
        )

    def _log_failure(
        self, returncode: int, stdout: str, stderr: str, cmd: list[str]
    ) -> None:
        parsed: dict[str, Any] = {}
        if isinstance(self._result, dict):
            parsed = self._result.get("parsed") or {}

        if parsed:
            logger.info(
                "fio terminated with rc=%s but produced valid metrics.", returncode
            )
            return

        logger.error("fio failed with return code %s", returncode)
        if stderr:
            logger.error("stderr: %s", stderr)


class FIOPlugin(SimpleWorkloadPlugin):
    """Plugin definition for FIO."""

    NAME = "fio"
    DESCRIPTION = "Flexible disk I/O via fio"
    CONFIG_CLS = FIOConfig
    GENERATOR_CLS = FIOGenerator
    REQUIRED_APT_PACKAGES = ["fio"]
    REQUIRED_LOCAL_TOOLS = ["fio"]
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"
    
    def get_preset_config(self, level: WorkloadIntensity) -> Optional[FIOConfig]:
        if level == WorkloadIntensity.LOW:
            return FIOConfig(
                rw="read",
                bs="1M",
                numjobs=1,
                iodepth=4,
                runtime=30
            )
        elif level == WorkloadIntensity.MEDIUM:
            return FIOConfig(
                rw="randrw",
                bs="4k",
                numjobs=4,
                iodepth=16,
                runtime=60
            )
        elif level == WorkloadIntensity.HIGH:
            return FIOConfig(
                rw="randwrite",
                bs="4k",
                numjobs=8,
                iodepth=64,
                runtime=120
            )
        return None

    def export_results_to_csv(
        self,
        results: List[Dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> List[Path]:
        """Export parsed fio metrics to a CSV file."""
        rows: list[dict[str, Any]] = []
        for entry in results:
            rep = entry.get("repetition")
            gen_result = entry.get("generator_result") or {}
            parsed = gen_result.get("parsed") or {}
            rows.append(
                {
                    "run_id": run_id,
                    "workload": test_name,
                    "repetition": rep,
                    "returncode": gen_result.get("returncode"),
                    "read_iops": parsed.get("read_iops"),
                    "read_bw_mb": parsed.get("read_bw_mb"),
                    "read_lat_ms": parsed.get("read_lat_ms"),
                    "write_iops": parsed.get("write_iops"),
                    "write_bw_mb": parsed.get("write_bw_mb"),
                    "write_lat_ms": parsed.get("write_lat_ms"),
                    "max_retries": gen_result.get("max_retries"), # Add inherited field
                    "tags": gen_result.get("tags"), # Add inherited field
                }
            )

        if not rows:
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{test_name}_plugin.csv"
        import pandas as pd

        pd.DataFrame(rows).to_csv(csv_path, index=False)
        return [csv_path]


PLUGIN = FIOPlugin()
