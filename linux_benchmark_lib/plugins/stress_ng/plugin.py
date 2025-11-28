"""
Stress-ng workload generator implementation.
Modular plugin version.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Type

from ..base_generator import BaseGenerator
from ..interface import WorkloadIntensity, WorkloadPlugin

logger = logging.getLogger(__name__)

@dataclass
class StressNGConfig:
    """Configuration for stress-ng workload generator."""
    
    cpu_workers: int = 0  # 0 means use all available CPUs
    cpu_method: str = "all"  # CPU stress method
    vm_workers: int = 1  # Virtual memory workers
    vm_bytes: str = "1G"  # Memory per VM worker
    io_workers: int = 1  # I/O workers
    timeout: int = 60  # Timeout in seconds
    metrics_brief: bool = True  # Use brief metrics output
    extra_args: List[str] = field(default_factory=list)


class StressNGGenerator(BaseGenerator):
    """Workload generator using stress-ng."""
    
    def __init__(self, config: StressNGConfig, name: str = "StressNGGenerator"):
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        
    def _build_command(self) -> List[str]:
        cmd = ["stress-ng"]
        if self.config.cpu_workers > 0:
            cmd.extend(["--cpu", str(self.config.cpu_workers)])
            cmd.extend(["--cpu-method", self.config.cpu_method])
        if self.config.vm_workers > 0:
            cmd.extend(["--vm", str(self.config.vm_workers)])
            cmd.extend(["--vm-bytes", self.config.vm_bytes])
        if self.config.io_workers > 0:
            cmd.extend(["--io", str(self.config.io_workers)])
        cmd.extend(["--timeout", f"{self.config.timeout}s"])
        if self.config.metrics_brief:
            cmd.append("--metrics-brief")
        cmd.extend(self.config.extra_args)
        return cmd
    
    def _validate_environment(self) -> bool:
        try:
            result = subprocess.run(["which", "stress-ng"], capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Error checking for stress-ng: {e}")
            return False
    
    def _run_command(self) -> None:
        cmd = self._build_command()
        logger.info(f"Running command: {' '.join(cmd)}")
        try:
            # Merge stderr into stdout to capture everything in one stream
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            
            output_lines = []
            safety_timeout = self.config.timeout + 5
            
            # Simple streaming loop (timeout handling is tricky here without select, 
            # but stress-ng handles its own timeout usually)
            while True:
                line = self._process.stdout.readline()
                if not line and self._process.poll() is not None:
                    break
                if line:
                    print(line, end='', flush=True)
                    output_lines.append(line)
            
            self._process.wait()
            stdout = "".join(output_lines)
            stderr = "" # Merged

            self._result = {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": self._process.returncode,
                "command": " ".join(cmd)
            }
            if self._process.returncode != 0:
                logger.error(f"stress-ng failed with return code {self._process.returncode}")
        except Exception as e:
            logger.error(f"Error running stress-ng: {e}")
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


class StressNGPlugin(WorkloadPlugin):
    """Plugin definition for StressNG."""
    
    @property
    def name(self) -> str:
        return "stress_ng"

    @property
    def description(self) -> str:
        return "CPU/IO/memory stress via stress-ng"

    @property
    def config_cls(self) -> Type[StressNGConfig]:
        return StressNGConfig

    def create_generator(self, config: StressNGConfig) -> StressNGGenerator:
        return StressNGGenerator(config)
    
    def get_preset_config(self, level: WorkloadIntensity) -> Optional[StressNGConfig]:
        if level == WorkloadIntensity.LOW:
            return StressNGConfig(
                cpu_workers=1,
                vm_workers=1,
                vm_bytes="128M",
                io_workers=0,
                timeout=30
            )
        elif level == WorkloadIntensity.MEDIUM:
            return StressNGConfig(
                cpu_workers=0, # All cores
                vm_workers=1,
                vm_bytes="50%", # 50% of available RAM
                io_workers=1,
                timeout=60,
                extra_args=["--cpu-load", "50"]
            )
        elif level == WorkloadIntensity.HIGH:
            return StressNGConfig(
                cpu_workers=0,
                cpu_method="matrixprod",
                vm_workers=2,
                vm_bytes="90%",
                io_workers=4,
                timeout=120
            )
        return None

    def get_required_apt_packages(self) -> List[str]:
        return ["stress-ng"]

    def get_required_local_tools(self) -> List[str]:
        return ["stress-ng"]

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

    def get_ansible_setup_path(self) -> Optional[Path]:
        path = Path(__file__).parent / "ansible" / "setup.yml"
        return path if path.exists() else None

    def get_ansible_teardown_path(self) -> Optional[Path]:
        path = Path(__file__).parent / "ansible" / "teardown.yml"
        return path if path.exists() else None

# Exposed Plugin Instance
PLUGIN = StressNGPlugin()
