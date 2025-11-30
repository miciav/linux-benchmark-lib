"""
FIO workload generator implementation.

This module uses fio (Flexible I/O Tester) to generate advanced disk I/O workloads.
"""

import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional, Type

from ..base_generator import BaseGenerator
from ..interface import WorkloadIntensity, WorkloadPlugin


logger = logging.getLogger(__name__)


@dataclass
class FIOConfig:
    """Configuration for fio I/O testing."""

    job_file: Optional[Path] = None
    runtime: int = 60
    rw: str = "randrw"
    bs: str = "4k"
    iodepth: int = 16
    numjobs: int = 1
    size: str = "1G"
    directory: str = "/tmp"
    name: str = "benchmark"
    output_format: str = "json"
    debug: bool = False


class FIOGenerator(BaseGenerator):
    """Workload generator using fio."""
    
    def __init__(self, config: FIOConfig, name: str = "FIOGenerator"):
        """
        Initialize the fio generator.
        
        Args:
            config: Configuration for fio
            name: Name of the generator
        """
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen] = None
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

        logger.debug("Built fio command with config: %s", asdict(self.config))
        
        return cmd
    
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
    
    def _run_command(self) -> None:
        """Run fio with configured parameters."""
        cmd = self._build_command()
        logger.info(f"Running command: {' '.join(cmd)}")
        logger.debug("Working directory: %s", self.config.directory)
        
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for process to complete
            stdout, stderr = self._process.communicate()
            logger.debug(
                "fio finished with rc=%s (stdout=%d chars, stderr=%d chars)",
                self._process.returncode,
                len(stdout or ""),
                len(stderr or ""),
            )
            
            # Parse results if JSON output
            parsed_result = {}
            if self.config.output_format == "json":
                logger.debug("Parsing fio JSON output")
                parsed_result = self._parse_json_output(stdout)
                logger.debug("Parsed fio JSON metrics: %s", parsed_result)
            
            # Store the result
            self._result = {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": self._process.returncode,
                "command": " ".join(cmd),
                "parsed": parsed_result
            }
            
            if self._process.returncode != 0:
                if parsed_result:
                    logger.info(
                        f"fio terminated with rc={self._process.returncode} but produced valid metrics."
                    )
                else:
                    logger.error(f"fio failed with return code {self._process.returncode}")
                    logger.error(f"stderr: {stderr}")
                
        except Exception as e:
            logger.error(f"Error running fio: {e}")
            self._result = {"error": str(e)}
        finally:
            self._process = None
            self._is_running = False
    
    def _stop_workload(self) -> None:
        """Stop fio process."""
        proc = self._process
        if proc and proc.poll() is None:
            logger.info("Terminating fio process")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing fio process")
                proc.kill()
                proc.wait()


class FIOPlugin(WorkloadPlugin):
    """Plugin definition for FIO."""
    
    @property
    def name(self) -> str:
        return "fio"

    @property
    def description(self) -> str:
        return "Flexible disk I/O via fio"

    @property
    def config_cls(self) -> Type[FIOConfig]:
        return FIOConfig

    def create_generator(self, config: FIOConfig) -> FIOGenerator:
        return FIOGenerator(config)
    
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

    def get_required_apt_packages(self) -> List[str]:
        return ["fio"]

    def get_required_local_tools(self) -> List[str]:
        return ["fio"]

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

    def get_ansible_setup_path(self) -> Optional[Path]:
        return Path(__file__).parent / "ansible" / "setup.yml"


PLUGIN = FIOPlugin()
