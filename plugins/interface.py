from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type

# We avoid importing BaseGenerator here to prevent circular imports,
# using TYPE_CHECKING or just Any for the return type in the signature.

class WorkloadPlugin(ABC):
    """
    Abstract base class for all workload plugins.
    
    A plugin encapsulates the logic for:
    1. Configuration (schema)
    2. Execution (Generator creation)
    3. Metadata (Name, description)
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

    def get_required_apt_packages(self) -> List[str]:
        """Return list of APT packages required by this plugin."""
        return []

    def get_required_pip_packages(self) -> List[str]:
        """Return list of Python packages required by this plugin."""
        return []
