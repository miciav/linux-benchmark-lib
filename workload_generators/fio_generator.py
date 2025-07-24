"""
FIO workload generator implementation.

This module uses fio (Flexible I/O Tester) to generate advanced disk I/O workloads.
"""

import subprocess
import json
import logging
from typing import Optional, List
from ._base_generator import BaseGenerator
from benchmark_config import FIOConfig


logger = logging.getLogger(__name__)


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
    
    def stop(self) -> None:
        """Stop fio if it's running."""
        if self._process and self._process.poll() is None:
            logger.info("Terminating fio process")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing fio process")
                self._process.kill()
                self._process.wait()
        
        super().stop()
