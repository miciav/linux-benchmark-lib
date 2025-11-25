"""
Geekbench 6 workload generator implementation.

This module handles downloading, installing (locally), and running Geekbench 6.
"""

import logging
import os
import platform
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Type

from ._base_generator import BaseGenerator
from plugins.interface import WorkloadPlugin

logger = logging.getLogger(__name__)


@dataclass
class GeekbenchConfig:
    """Configuration for Geekbench 6 workload."""
    
    version: str = "6.3.0"
    url_override: Optional[str] = None
    upload: bool = True
    timeout: int = 600  # 10 minutes


class GeekbenchGenerator(BaseGenerator):
    """Workload generator using Geekbench 6."""

    def __init__(self, config: GeekbenchConfig, name: str = "GeekbenchGenerator"):
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        # Cache directory for geekbench binary
        self._cache_dir = Path(os.path.expanduser("~/.cache/linux-benchmark/geekbench"))
        self._binary_path: Optional[Path] = None

    def _get_download_url(self) -> str:
        if self.config.url_override:
            return self.config.url_override
        
        machine = platform.machine().lower()
        if machine in ["aarch64", "arm64"]:
            # ARM Preview URL
            return f"https://cdn.geekbench.com/Geekbench-{self.config.version}-LinuxARMPreview.tar.gz"
            
        # Default URL pattern for Linux x86_64
        return f"https://cdn.geekbench.com/Geekbench-{self.config.version}-Linux.tar.gz"

    def _prepare_environment(self) -> bool:
        """Download and extract Geekbench if not present."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        
        url = self._get_download_url()
        filename = url.split("/")[-1]
        
        # Guess the extract directory name based on filename
        extract_dir_name = filename.replace(".tar.gz", "")
        extract_dir = self._cache_dir / extract_dir_name
        
        binary_name = "geekbench6"
        
        # Check if already extracted in the expected directory
        if extract_dir.exists():
            potential_binary = extract_dir / binary_name
            if potential_binary.exists():
                self._binary_path = potential_binary
                return True
        
        tar_path = self._cache_dir / filename
        
        logger.info(f"Downloading Geekbench from {url}...")
        try:
            subprocess.run(["wget", "-O", str(tar_path), url], check=True)
        except subprocess.CalledProcessError:
            logger.error(f"Failed to download Geekbench from {url}")
            return False
            
        logger.info(f"Extracting Geekbench to {self._cache_dir}...")
        try:
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=self._cache_dir)
        except Exception as e:
            logger.error(f"Failed to extract Geekbench: {e}")
            return False
            
        # Locate binary after extraction
        if extract_dir.exists():
             potential_binary = extract_dir / binary_name
             if potential_binary.exists():
                 self._binary_path = potential_binary
                 return True

        # Fallback search
        for path in self._cache_dir.rglob(binary_name):
            if path.is_file() and os.access(path, os.X_OK):
                self._binary_path = path
                return True
                
        logger.error("Could not locate geekbench6 binary after extraction.")
        return False

    def _build_command(self) -> List[str]:
        if not self._binary_path:
            raise RuntimeError("Geekbench binary not found. Environment setup failed?")
            
        cmd = [str(self._binary_path)]
        return cmd

    def _validate_environment(self) -> bool:
        return shutil.which("wget") is not None

    def _run_command(self) -> None:
        if not self._prepare_environment():
            self._result = {"error": "Failed to prepare Geekbench environment"}
            return

        cmd = self._build_command()
        logger.info(f"Running command: {' '.join(cmd)}")
        
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            try:
                stdout, stderr = self._process.communicate(timeout=self.config.timeout)
            except subprocess.TimeoutExpired:
                logger.error(f"Geekbench timed out after {self.config.timeout}s")
                self._process.kill()
                stdout, stderr = self._process.communicate()
                self._result = {"error": "TimeoutExpired", "stdout": stdout, "stderr": stderr}
                return

            self._result = {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": self._process.returncode,
                "command": " ".join(cmd)
            }
            
            if self._process.returncode != 0:
                logger.error(f"Geekbench failed with return code {self._process.returncode}")
                if stdout: logger.error(f"stdout: {stdout}")
                if stderr: logger.error(f"stderr: {stderr}")
                
        except Exception as e:
            logger.error(f"Error running Geekbench: {e}")
            self._result = {"error": str(e)}
        finally:
            self._process = None
            self._is_running = False

    def _stop_workload(self) -> None:
        proc = self._process
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


class GeekbenchPlugin(WorkloadPlugin):
    """Plugin definition for Geekbench."""
    
    @property
    def name(self) -> str:
        return "geekbench"

    @property
    def description(self) -> str:
        return "Cross-platform benchmark (Geekbench 6)"

    @property
    def config_cls(self) -> Type[GeekbenchConfig]:
        return GeekbenchConfig

    def create_generator(self, config: GeekbenchConfig) -> GeekbenchGenerator:
        return GeekbenchGenerator(config)
    
    def get_required_apt_packages(self) -> List[str]:
        return ["wget", "tar", "gzip"]

# Exposed Plugin Instance
PLUGIN = GeekbenchPlugin()
