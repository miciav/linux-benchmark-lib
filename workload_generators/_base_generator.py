"""
Base generator abstract class for workload generators.

This module defines the common interface that all workload generators must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import threading
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class BaseGenerator(ABC):
    """Abstract base class for all workload generators."""
    
    def __init__(self, name: str):
        """
        Initialize the base generator.

        Args:
            name: Name of the generator
        """
        self.name = name
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._result: Optional[Any] = None
    
    @abstractmethod
    def _run_command(self) -> None:
        """
        Run the actual command or process to generate workload.

        This method should handle the process of workload generation.
        """
        pass

    @abstractmethod
    def _validate_environment(self) -> bool:
        """
        Validate that the generator can run in the current environment.

        Returns:
            True if the environment is valid, False otherwise
        """
        pass

    def start(self) -> None:
        """Start the workload generation in a background thread."""
        if self._is_running:
            logger.warning(f"{self.name} generator is already running")
            return

        if not self._validate_environment():
            raise RuntimeError(f"{self.name} generator cannot run in this environment")

        self._is_running = True
        self._thread = threading.Thread(target=self._run_command)
        self._thread.start()

        logger.info(f"{self.name} generator started")

    def stop(self) -> None:
        """Stop the workload generation."""
        if not self._is_running:
            logger.warning(f"{self.name} generator is not running")
            return
            
        self._is_running = False
        if self._thread:
            self._thread.join()
            
        logger.info(f"{self.name} generator stopped")

    def get_result(self) -> Any:
        """
        Get the result of the workload generation.

        Returns:
            The result obtained from the workload generation
        """
        return self._result
