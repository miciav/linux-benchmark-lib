"""
FIO workload generator implementation.

This module uses fio (Flexible I/O Tester) to generate advanced disk I/O workloads.
"""

import json
import logging
import subprocess
from dataclasses import dataclass
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
        
    def _build_command(self) -> List[str]:
        """
        Build the fio command from configuration.
        
        Returns:
            List of command arguments
        """
        cmd = ["fio"]
        
        # If a job file is provided, use it
        if self.config.job_file:
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
        try:
            data = json.loads(output)
            
            # Extract key metrics from the first job
            if data.get("jobs") and len(data["jobs"]) > 0:
                job = data["jobs"][0]
                
                result = {
                    "read_iops": job.get("read", {}).get("iops", 0),
                    "read_bw_mb": job.get("read", {}).get("bw", 0) / 1024,  # Convert KB to MB
                    "read_lat_ms": job.get("read", {}).get("lat_ns", {}).get("mean", 0) / 1e6,  # Convert ns to ms
                    "write_iops": job.get("write", {}).get("iops", 0),
                    "write_bw_mb": job.get("write", {}).get("bw", 0) / 1024,
                    "write_lat_ms": job.get("write", {}).get("lat_ns", {}).get("mean", 0) / 1e6,
                }
                
                return result
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse fio JSON output: {e}")
            
        return {}
    
    def _run_command(self) -> None:
        """Run fio with configured parameters."""
        cmd = self._build_command()
        logger.info(f"Running command: {' '.join(cmd)}")
        
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for process to complete
            stdout, stderr = self._process.communicate()
            
            # Parse results if JSON output
            parsed_result = {}
            if self.config.output_format == "json":
                parsed_result = self._parse_json_output(stdout)
            
            # Store the result
            self._result = {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": self._process.returncode,
                "command": " ".join(cmd),
                "parsed": parsed_result
            }
            
            if self._process.returncode != 0:
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


PLUGIN = FIOPlugin()
