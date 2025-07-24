"""
Stress-ng workload generator implementation.

This module uses stress-ng to generate various types of system load.
"""

import subprocess
import logging
from typing import Optional, List
from ._base_generator import BaseGenerator
from benchmark_config import StressNGConfig


logger = logging.getLogger(__name__)


class StressNGGenerator(BaseGenerator):
    """Workload generator using stress-ng."""
    
    def __init__(self, config: StressNGConfig, name: str = "StressNGGenerator"):
        """
        Initialize the stress-ng generator.
        
        Args:
            config: Configuration for stress-ng
            name: Name of the generator
        """
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        
    def _build_command(self) -> List[str]:
        """
        Build the stress-ng command from configuration.
        
        Returns:
            List of command arguments
        """
        cmd = ["stress-ng"]
        
        # CPU stress options
        if self.config.cpu_workers > 0:
            cmd.extend(["--cpu", str(self.config.cpu_workers)])
            cmd.extend(["--cpu-method", self.config.cpu_method])
        
        # Memory stress options
        if self.config.vm_workers > 0:
            cmd.extend(["--vm", str(self.config.vm_workers)])
            cmd.extend(["--vm-bytes", self.config.vm_bytes])
        
        # I/O stress options
        if self.config.io_workers > 0:
            cmd.extend(["--io", str(self.config.io_workers)])
        
        # Timeout
        cmd.extend(["--timeout", f"{self.config.timeout}s"])
        
        # Metrics
        if self.config.metrics_brief:
            cmd.append("--metrics-brief")
        
        # Extra arguments
        cmd.extend(self.config.extra_args)
        
        return cmd
    
    def _validate_environment(self) -> bool:
        """
        Validate that stress-ng is available.
        
        Returns:
            True if stress-ng is available, False otherwise
        """
        try:
            result = subprocess.run(
                ["which", "stress-ng"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Error checking for stress-ng: {e}")
            return False
    
    def _run_command(self) -> None:
        """Run stress-ng with configured parameters."""
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
            
            # Store the result
            self._result = {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": self._process.returncode,
                "command": " ".join(cmd)
            }
            
            if self._process.returncode != 0:
                logger.error(f"stress-ng failed with return code {self._process.returncode}")
                logger.error(f"stderr: {stderr}")
                
        except Exception as e:
            logger.error(f"Error running stress-ng: {e}")
            self._result = {"error": str(e)}
        finally:
            self._process = None
            self._is_running = False
    
    def stop(self) -> None:
        """Stop stress-ng if it's running."""
        if self._process and self._process.poll() is None:
            logger.info("Terminating stress-ng process")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing stress-ng process")
                self._process.kill()
                self._process.wait()
        
        super().stop()
