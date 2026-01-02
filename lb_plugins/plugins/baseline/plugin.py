"""
Baseline workload generator implementation.
This plugin performs no actual work, allowing the system to measure baseline performance/overhead.
"""

import logging
import threading
import time
# Removed from dataclasses import dataclass
from typing import Optional

from pydantic import Field # Added pydantic Field

from ...base_generator import BaseGenerator
from ...interface import WorkloadIntensity, SimpleWorkloadPlugin, BasePluginConfig # Imported BasePluginConfig

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


class BaselinePlugin(SimpleWorkloadPlugin):
    """Plugin definition for Baseline (Idle)."""

    NAME = "baseline"
    DESCRIPTION = "Idle workload to measure system baseline performance"
    CONFIG_CLS = BaselineConfig
    GENERATOR_CLS = BaselineGenerator
    REQUIRED_APT_PACKAGES: list[str] = []
    REQUIRED_LOCAL_TOOLS: list[str] = []
    
    def get_preset_config(self, level: WorkloadIntensity) -> Optional[BaselineConfig]:
        if level == WorkloadIntensity.LOW:
            return BaselineConfig(duration=30)
        elif level == WorkloadIntensity.MEDIUM:
            return BaselineConfig(duration=60)
        elif level == WorkloadIntensity.HIGH:
            return BaselineConfig(duration=300)
        return None

# Exposed Plugin Instance
PLUGIN = BaselinePlugin()
