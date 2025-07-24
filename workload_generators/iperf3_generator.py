"""
Iperf3 workload generator implementation.

This module uses iperf3 to generate network traffic.
"""

import iperf3
import logging
from typing import Optional
from ._base_generator import BaseGenerator
from benchmark_config import IPerf3Config


logger = logging.getLogger(__name__)


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
        self.client = iperf3.Client()

    def _validate_environment(self) -> bool:
        """
        Validate that iperf3 is available.

        Returns:
            True if iperf3 is available, False otherwise
        """
        try:
            iperf3.Client()
            return True
        except Exception as e:
            logger.error(f"Error creating iperf3 client: {e}")
            return False

    def _run_command(self) -> None:
        """Run iperf3 with configured parameters."""
        logger.info("Starting iperf3 test")

        self.client.server_hostname = self.config.server_host
        self.client.port = self.config.server_port
        self.client.protocol = self.config.protocol
        self.client.num_streams = self.config.parallel
        self.client.duration = self.config.time
        self.client.reverse = self.config.reverse
        if self.config.bandwidth:
            self.client.bandwidth = self.config.bandwidth

        try:
            result = self.client.run()
            self._result = {
                "error": result.error if result.error else None,
                "stdout": str(result)
            }
        except Exception as e:
            logger.error(f"Error running iperf3: {e}")
            self._result = {"error": str(e)}

    def stop(self) -> None:
        """Stop iperf3 client."""
        logger.info("Stopping iperf3 client")
        super().stop()
