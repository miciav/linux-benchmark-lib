"""
Iperf3 workload generator implementation.

This module uses iperf3 to generate network traffic.
"""

import ctypes.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Type

import iperf3

from ..base_generator import BaseGenerator
from ..interface import WorkloadIntensity, WorkloadPlugin


logger = logging.getLogger(__name__)


@dataclass
class IPerf3Config:
    """Configuration for iperf3 network testing."""

    server_host: str = "localhost"
    server_port: int = 5201
    protocol: str = "tcp"
    parallel: int = 1
    time: int = 60
    bandwidth: Optional[str] = None
    reverse: bool = False
    json_output: bool = True
    debug: bool = False


class IPerf3Generator(BaseGenerator):
    """Workload generator using iperf3."""

    def __init__(self, config: IPerf3Config, name: str = "IPerf3Generator"):
        """
        Initialize the iperf3 generator.

        Args:
            config: Configuration for iperf3
            name: Name of the generator
        """
        super().__init__(name)
        self.config = config
        self.client: Optional[iperf3.Client] = None

    def _validate_environment(self) -> bool:
        """
        Validate that iperf3 is available.

        Returns:
            True if iperf3 is available, False otherwise
        """
        lib = ctypes.util.find_library("iperf")
        if not lib:
            logger.error("iperf3 shared library not found (libiperf). Install iperf3.")
            return False
        try:
            self.client = iperf3.Client()
            return True
        except Exception as e:
            logger.error(f"Error creating iperf3 client: {e}")
            self.client = None
            return False

    def _run_command(self) -> None:
        """Run iperf3 with configured parameters."""
        logger.info("Starting iperf3 test")

        if self.client is None:
            self._result = {"error": "iperf3 client not initialized"}
            return

        self.client.server_hostname = self.config.server_host
        self.client.port = self.config.server_port
        self.client.protocol = self.config.protocol
        self.client.num_streams = self.config.parallel
        self.client.duration = self.config.time
        self.client.reverse = self.config.reverse
        if self.config.bandwidth:
            self.client.bandwidth = self.config.bandwidth
        if self.config.debug:
            self.client.verbose = True

        try:
            result = self.client.run()
            self._result = {
                "error": result.error if result.error else None,
                "stdout": str(result)
            }
        except Exception as e:
            logger.error(f"Error running iperf3: {e}")
            self._result = {"error": str(e)}

    def _stop_workload(self) -> None:
        """Stop iperf3 client."""
        logger.info("Stopping iperf3 client (no-op as iperf3 client is blocking)")
        # iperf3 client.run() is blocking and doesn't expose a stop method
        # In a real implementation, we might need to run it in a separate process
        # similar to other generators if we need hard stopping capability.
        pass


class IPerf3Plugin(WorkloadPlugin):
    """Plugin definition for iperf3."""

    @property
    def name(self) -> str:
        return "iperf3"

    @property
    def description(self) -> str:
        return "Network throughput via iperf3 client"

    @property
    def config_cls(self) -> Type[IPerf3Config]:
        return IPerf3Config

    def create_generator(self, config: IPerf3Config) -> IPerf3Generator:
        return IPerf3Generator(config)

    def get_preset_config(self, level: WorkloadIntensity) -> Optional[IPerf3Config]:
        if level == WorkloadIntensity.LOW:
            return IPerf3Config(
                parallel=1,
                time=30,
                protocol="tcp"
            )
        elif level == WorkloadIntensity.MEDIUM:
            return IPerf3Config(
                parallel=4,
                time=60,
                protocol="tcp"
            )
        elif level == WorkloadIntensity.HIGH:
            return IPerf3Config(
                parallel=8,
                time=120,
                protocol="tcp"
            )
        return None

    def get_required_apt_packages(self) -> List[str]:
        return ["iperf3", "libiperf0"]
    
    def get_required_pip_packages(self) -> List[str]:
        return ["iperf3"]

    def get_required_local_tools(self) -> List[str]:
        return ["iperf3"]

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"


PLUGIN = IPerf3Plugin()
