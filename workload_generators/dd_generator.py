"""
DD workload generator implementation.

This module uses dd command to generate disk I/O load.
"""

import subprocess
import logging
import os
from typing import Optional, List
from ._base_generator import BaseGenerator
from benchmark_config import DDConfig


logger = logging.getLogger(__name__)


class DDGenerator(BaseGenerator):
    """Workload generator using dd command."""
    
    def __init__(self, config: DDConfig, name: str = "DDGenerator"):
        """
        Initialize the dd generator.
        
        Args:
            config: Configuration for dd
            name: Name of the generator
        """
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        
    def _build_command(self) -> List[str]:
        """
        Build the dd command from configuration.
        
        Returns:
            List of command arguments
        """
        cmd = ["dd"]
        
        # Input file
        cmd.append(f"if={self.config.if_path}")
        
        # Output file
        cmd.append(f"of={self.config.of_path}")
        
        # Block size
        cmd.append(f"bs={self.config.bs}")
        
        # Count
        cmd.append(f"count={self.config.count}")
        
        # Conversion options
        if self.config.conv:
            cmd.append(f"conv={self.config.conv}")
        
        # Output flags
        if self.config.oflag:
            cmd.append(f"oflag={self.config.oflag}")
        
        # Show progress
        cmd.append("status=progress")
        
        return cmd
    
    def _validate_environment(self) -> bool:
        """
        Validate that dd is available and output path is writable.
        
        Returns:
            True if dd is available and path is writable, False otherwise
        """
        # Check if dd is available
        try:
            result = subprocess.run(
                ["which", "dd"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.error("dd command not found")
                return False
        except Exception as e:
            logger.error(f"Error checking for dd: {e}")
            return False
        
        # Check if output directory is writable
        output_dir = os.path.dirname(self.config.of_path)
        if not os.access(output_dir, os.W_OK):
            logger.error(f"Output directory {output_dir} is not writable")
            return False
        
        return True
    
    def _run_command(self) -> None:
        """Run dd with configured parameters."""
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
                logger.error(f"dd failed with return code {self._process.returncode}")
                logger.error(f"stderr: {stderr}")
            
            # Clean up the test file
            if os.path.exists(self.config.of_path) and self.config.of_path.startswith("/tmp/"):
                os.remove(self.config.of_path)
                logger.info(f"Cleaned up test file: {self.config.of_path}")
                
        except Exception as e:
            logger.error(f"Error running dd: {e}")
            self._result = {"error": str(e)}
        finally:
            self._process = None
            self._is_running = False
    
    def stop(self) -> None:
        """Stop dd if it's running."""
        if self._process and self._process.poll() is None:
            logger.info("Terminating dd process")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing dd process")
                self._process.kill()
                self._process.wait()
        
        super().stop()
