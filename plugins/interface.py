from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

class WorkloadIntensity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    USER_DEFINED = "user_defined"

class WorkloadPlugin(ABC):
    """
    Abstract base class for all workload plugins.
    
    A plugin encapsulates the logic for:
    1. Configuration (schema)
    2. Execution (Generator creation)
    3. Metadata (Name, description)
    4. Assets (Dockerfile, Ansible playbooks)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the workload (e.g., 'stress_ng')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        pass

    @property
    @abstractmethod
    def config_cls(self) -> Type[Any]:
        """
        The DataClass or Pydantic model used for configuration.
        The ConfigService will use this to deserialize raw JSON.
        """
        pass

    @abstractmethod
    def create_generator(self, config: Any) -> Any:
        """
        Create a new instance of the workload generator.
        
        Args:
            config: An instance of self.config_cls
        """
        pass
    
    def get_preset_config(self, level: WorkloadIntensity) -> Optional[Any]:
        """
        Return a configuration object for the specified intensity level.
        If USER_DEFINED or not implemented, return None.
        """
        return None

    def get_required_apt_packages(self) -> List[str]:
        """Return list of APT packages required by this plugin."""
        return []

    def get_required_pip_packages(self) -> List[str]:
        """Return list of Python packages required by this plugin."""
        return []

    def get_required_local_tools(self) -> List[str]:
        """
        Return list of command-line tools required by this plugin for local execution.
        Used by `lb doctor` to verify the local environment.
        """
        return []

    def get_dockerfile_path(self) -> Optional[Path]:
        """
        Return the path to the Dockerfile for this plugin.
        The platform will build a dedicated image from this file.
        """
        return None

    def get_ansible_setup_path(self) -> Optional[Path]:
        """
        Return the path to the Ansible setup playbook.
        Executed before the workload runs on remote hosts.
        """
        return None

    def get_ansible_teardown_path(self) -> Optional[Path]:
        """
        Return the path to the Ansible teardown playbook.
        Executed after the workload runs (even on failure) on remote hosts.
        """
        return None
