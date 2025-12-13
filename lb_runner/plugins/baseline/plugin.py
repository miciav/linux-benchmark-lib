"""
Baseline workload generator implementation.
This plugin performs no actual work, allowing the system to measure baseline performance/overhead.
"""

import logging
import threading
import time
# Removed from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Type

from pydantic import Field # Added pydantic Field

from ...plugin_system.base_generator import BaseGenerator
from ...plugin_system.interface import WorkloadIntensity, WorkloadPlugin, BasePluginConfig # Imported BasePluginConfig

logger = logging.getLogger(__name__)

class BaselineConfig(BasePluginConfig):
    """Configuration for baseline workload generator."""
    duration: float = Field(default=60.0, gt=0, description="Duration to sleep in seconds") # Using Pydantic Field, changed to float


class BaselineGenerator(BaseGenerator):
    """Workload generator that does nothing (sleeps) to establish a baseline."""
    
    def __init__(self, config: BaselineConfig, name: str = "BaselineGenerator"):
        super().__init__(name)
        self.config = config
        self._stop_event = threading.Event()
        
    def _run_command(self) -> None:
        logger.info(f"Starting baseline run for {self.config.duration} seconds")
        
        start_time = time.time()
        # Wait for the duration or until stopped
        stopped_early = self._stop_event.wait(self.config.duration)
        end_time = time.time()
        
        actual_duration = end_time - start_time
        
        self._result = {
            "status": "completed" if not stopped_early else "stopped",
            "target_duration": self.config.duration,
            "actual_duration": actual_duration,
            "workload": "idle",
            "max_retries": self.config.max_retries, # Example of using inherited field
            "tags": self.config.tags # Example of using inherited field
        }
        
        logger.info(f"Baseline run finished. Actual duration: {actual_duration:.2f}s")

    def _validate_environment(self) -> bool:
        # Baseline requires no external tools
        return True
    
    def _stop_workload(self) -> None:
        self._stop_event.set()


class BaselinePlugin(WorkloadPlugin):
    """Plugin definition for Baseline (Idle)."""
    
    @property
    def name(self) -> str:
        return "baseline"

    @property
    def description(self) -> str:
        return "Idle workload to measure system baseline performance"

    @property
    def config_cls(self) -> Type[BaselineConfig]:
        return BaselineConfig

    def create_generator(self, config: BaselineConfig) -> BaselineGenerator:
        return BaselineGenerator(config)
    
    def get_preset_config(self, level: WorkloadIntensity) -> Optional[BaselineConfig]:
        if level == WorkloadIntensity.LOW:
            return BaselineConfig(duration=30)
        elif level == WorkloadIntensity.MEDIUM:
            return BaselineConfig(duration=60)
        elif level == WorkloadIntensity.HIGH:
            return BaselineConfig(duration=300)
        return None

    def get_required_apt_packages(self) -> List[str]:
        return []

    def get_required_local_tools(self) -> List[str]:
        return []

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

# Exposed Plugin Instance
PLUGIN = BaselinePlugin()
