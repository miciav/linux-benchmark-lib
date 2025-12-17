from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
import yaml # Added yaml import

import pandas as pd
from pydantic import BaseModel, Field # Added Pydantic imports


class WorkloadIntensity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    USER_DEFINED = "user_defined"


class BasePluginConfig(BaseModel):
    """Base model for common plugin configuration fields."""
    max_retries: int = Field(default=0, ge=0, description="Maximum number of retries for the workload")
    timeout_buffer: int = Field(default=10, description="Safety buffer in seconds added to expected runtime")
    tags: List[str] = Field(default_factory=list, description="Tags associated with the workload")

    model_config = {
        "extra": "ignore" # Ignore extra fields in YAML not defined in the model
    }

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
    def config_cls(self) -> Type[BasePluginConfig]: # Changed return type hint
        """
        The Pydantic model used for configuration.
        The ConfigService will use this to deserialize raw JSON.
        """
        pass

    @abstractmethod
    def create_generator(self, config: BasePluginConfig) -> Any: # Changed type hint
        """
        Create a new instance of the workload generator.
        
        Args:
            config: An instance of self.config_cls
        """
        pass
    
    def load_config_from_file(self, config_file_path: Path) -> BasePluginConfig:
        """
        Loads and validates plugin configuration from a YAML file.

        The method merges common configuration (from the 'common' section)
        with plugin-specific configuration (from the 'plugins.<plugin_name>' section).
        Plugin-specific settings override common settings.
        Finally, the merged configuration is validated against `self.config_cls`.

        Args:
            config_file_path: The path to the YAML configuration file.

        Returns:
            An instance of `self.config_cls` with the loaded and validated configuration.

        Raises:
            FileNotFoundError: If the config_file_path does not exist.
            yaml.YAMLError: If the file content is not valid YAML.
            ValidationError: If the merged configuration does not conform to `self.config_cls` schema.
        """
        if not config_file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file_path}")

        with open(config_file_path, 'r') as f:
            full_data = yaml.safe_load(f) or {}

        # Extract common and plugin-specific data
        common_data = full_data.get("common", {})
        plugin_data = full_data.get("plugins", {}).get(self.name, {})

        # Merge data: plugin-specific overrides common
        merged_data = {**common_data, **plugin_data}

        # Validate and instantiate the config class using Pydantic
        # Pydantic will handle default values for missing fields
        return self.config_cls(**merged_data)
    
    def get_preset_config(self, level: WorkloadIntensity) -> Optional[BasePluginConfig]: # Changed type hint
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

    def get_ansible_setup_extravars(self) -> Dict[str, Any]:
        """Return extra vars merged into the plugin setup playbook run."""
        return {}

    def get_ansible_teardown_extravars(self) -> Dict[str, Any]:
        """Return extra vars merged into the plugin teardown playbook run."""
        return {}

    # Optional: allow plugins to normalize their own results into CSV before collection
    def export_results_to_csv(
        self,
        results: List[Dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> List[Path]:
        """
        Normalize plugin-specific results into CSV files stored in output_dir.

        Default implementation flattens generator_result and metadata into a single CSV.
        Plugins with richer report formats can override to write multiple CSVs.
        """
        rows: list[dict[str, Any]] = []
        for entry in results:
            row = {
                "run_id": run_id,
                "workload": test_name,
                "repetition": entry.get("repetition"),
                "duration_seconds": entry.get("duration_seconds"),
                "success": entry.get("success"),
            }
            gen_result = entry.get("generator_result") or {}
            if isinstance(gen_result, dict):
                for key, value in gen_result.items():
                    row[f"generator_{key}"] = value
            rows.append(row)

        if not rows:
            return []

        df = pd.DataFrame(rows)
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{test_name}_plugin.csv"
        df.to_csv(csv_path, index=False)
        return [csv_path]
