"""Benchmark configuration (canonical runner/controller definition)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from inspect import isclass

from pydantic import BaseModel, Field, model_validator, ValidationError, model_serializer # Added Pydantic imports

# --- Ansible Root Definition ---
_HERE = Path(__file__).resolve()
_DEFAULT_ANSIBLE_ROOT = _HERE.parent / "ansible"
_ALT_ANSIBLE_ROOT = _HERE.parent.parent / "lb_controller" / "ansible"
# Prefer the controller-anchored Ansible assets; fall back to a local folder if present.
if _ALT_ANSIBLE_ROOT.exists():
    ANSIBLE_ROOT = _ALT_ANSIBLE_ROOT
else:
    ANSIBLE_ROOT = _DEFAULT_ANSIBLE_ROOT
logger = logging.getLogger(__name__)

# --- Pydantic Models for Configuration ---


class PerfConfig(BaseModel):
    """Configuration for perf profiling."""

    events: List[str] = Field(
        default_factory=lambda: [
            "cpu-cycles",
            "instructions",
            "cache-references",
            "cache-misses",
            "branches",
            "branch-misses",
        ],
        description="List of perf events to monitor",
    )
    interval_ms: int = Field(default=1000, gt=0, description="Sampling interval in milliseconds")
    pid: Optional[int] = Field(default=None, gt=0, description="Process ID to profile")
    cpu: Optional[int] = Field(default=None, ge=0, description="CPU to profile")


class MetricCollectorConfig(BaseModel):
    """Configuration for metric collectors."""

    psutil_interval: float = Field(default=1.0, gt=0, description="Interval for psutil collector in seconds")
    cli_commands: List[str] = Field(
        default_factory=lambda: [
            "sar -u 1 1",
            "vmstat 1 1",
            "iostat -d 1 1",
            "mpstat 1 1",
            "pidstat -h 1 1",
        ],
        description="List of CLI commands to execute for metric collection",
    )
    perf_config: PerfConfig = Field(default_factory=PerfConfig, description="Configuration for perf profiling")
    enable_ebpf: bool = Field(default=False, description="Enable eBPF-based metric collection")


class RemoteHostConfig(BaseModel):
    """Configuration for a remote benchmark host."""

    name: str = Field(description="Unique name for the remote host")
    address: str = Field(description="IP address or hostname of the remote host")
    port: int = Field(default=22, gt=0, description="SSH port for connection")
    user: str = Field(default="root", description="SSH user for connection")
    become: bool = Field(default=True, description="Use Ansible become (sudo) for escalated privileges")
    become_method: str = Field(default="sudo", description="Ansible become method")
    vars: Dict[str, Any] = Field(default_factory=dict, description="Additional Ansible variables for this host")

    @model_validator(mode="after")
    def validate_name_not_empty(self) -> 'RemoteHostConfig':
        if not self.name or not self.name.strip():
            raise ValueError("RemoteHostConfig: 'name' must be non-empty")
        return self

    def ansible_host_line(self) -> str:
        """Render an INI-style inventory line for this host (compat helper)."""
        parts = [
            self.name,
            f"ansible_host={self.address}",
            f"ansible_port={self.port}",
            f"ansible_user={self.user}",
        ]
        if self.become:
            parts.append("ansible_become=true")
        if self.become_method:
            parts.append(f"ansible_become_method={self.become_method}")
        for key, value in self.vars.items():
            val = str(value)
            if " " in val:
                val = f'"{val}"'
            parts.append(f"{key}={val}")
        return " ".join(parts)


class RemoteExecutionConfig(BaseModel):
    """Configuration for remote execution via Ansible."""

    enabled: bool = Field(default=False, description="Enable remote execution")
    inventory_path: Optional[Path] = Field(default=None, description="Path to a custom Ansible inventory file")
    run_setup: bool = Field(default=True, description="Execute setup playbooks before tests")
    run_collect: bool = Field(default=True, description="Execute collection playbooks after tests")
    setup_playbook: Path = Field(default_factory=lambda: ANSIBLE_ROOT / "playbooks" / "setup.yml", description="Path to the Ansible setup playbook")
    run_playbook: Path = Field(default_factory=lambda: ANSIBLE_ROOT / "playbooks" / "run_benchmark.yml", description="Path to the Ansible run playbook")
    collect_playbook: Path = Field(default_factory=lambda: ANSIBLE_ROOT / "playbooks" / "collect.yml", description="Path to the Ansible collect playbook")
    teardown_playbook: Path = Field(default_factory=lambda: ANSIBLE_ROOT / "playbooks" / "teardown.yml", description="Path to the Ansible teardown playbook")
    run_teardown: bool = Field(default=True, description="Execute teardown playbooks after tests")
    use_container_fallback: bool = Field(default=False, description="Use container-based fallback for remote execution")

    @model_validator(mode="after")
    def _normalize_playbook_paths(self) -> 'RemoteExecutionConfig':
        """Map legacy playbook paths to the current ansible root when needed."""
        roots = [
            ANSIBLE_ROOT,
            Path(__file__).resolve().parent / "ansible", # Local ansible dir
            Path(__file__).resolve().parent.parent / "lb_controller" / "ansible", # Controller ansible dir
        ]
        playbooks = {
            "setup_playbook": "setup.yml",
            "run_playbook": "run_benchmark.yml",
            "collect_playbook": "collect.yml",
            "teardown_playbook": "teardown.yml",
        }
        for attr, fname in playbooks.items():
            path: Path = getattr(self, attr)
            if path and path.exists():
                continue # Already a valid path
            
            # Check if the default factory created a non-existent path
            # (e.g. if ANSIBLE_ROOT points to a non-existent controller dir)
            default_path = Field(default_factory=lambda: ANSIBLE_ROOT / "playbooks" / fname).default_factory()
            if path == default_path and not path.exists():
                # If it's the default path and it doesn't exist, try alternative roots
                for root in roots:
                    candidate = root / "playbooks" / fname
                    if candidate.exists():
                        setattr(self, attr, candidate)
                        break
        return self


class WorkloadConfig(BaseModel):
    """Configuration wrapper for workload plugins."""

    plugin: str = Field(description="Name of the plugin to use")
    enabled: bool = Field(default=True, description="Enable or disable this workload")
    intensity: str = Field(default="user_defined", description="Pre-defined intensity level (low, medium, high, user_defined)")
    options: Dict[str, Any] = Field(default_factory=dict, description="Plugin-specific options for the workload")


class BenchmarkConfig(BaseModel):
    """Main configuration for benchmark tests."""

    # Test execution parameters
    repetitions: int = Field(default=3, gt=0, description="Number of repetitions for each test")
    test_duration_seconds: int = Field(default=3600, gt=0, description="Default duration for tests in seconds")
    metrics_interval_seconds: float = Field(default=1.0, gt=0, description="Interval for metric collection in seconds")
    warmup_seconds: int = Field(default=5, ge=0, description="Warmup period before metric collection starts")
    cooldown_seconds: int = Field(default=5, ge=0, description="Cooldown period after test finishes")

    # Output configuration
    output_dir: Path = Field(default=Path("./benchmark_results"), description="Root directory for all benchmark output")
    report_dir: Path = Field(default=Path("./reports"), description="Directory for generated reports")
    data_export_dir: Path = Field(default=Path("./data_exports"), description="Directory for raw data exports")

    # Dynamic Plugin Settings (The new way: Pydantic models for specific plugin configs)
    plugin_settings: Dict[str, Any] = Field(default_factory=dict, description="Dictionary of plugin-specific Pydantic config models")

    # Metric collector configuration
    collectors: MetricCollectorConfig = Field(default_factory=MetricCollectorConfig, description="Configuration for metric collectors")

    # Workload plugin configuration (name -> WorkloadConfig)
    workloads: Dict[str, WorkloadConfig] = Field(default_factory=dict, description="Dictionary of workload definitions")

    # Remote execution configuration
    remote_hosts: List[RemoteHostConfig] = Field(default_factory=list, description="List of remote hosts for benchmarking")
    remote_execution: RemoteExecutionConfig = Field(default_factory=RemoteExecutionConfig, description="Configuration for remote execution")

    # System information collection
    collect_system_info: bool = Field(default=True, description="Collect system information before running benchmarks")

    # InfluxDB configuration (optional)
    influxdb_enabled: bool = Field(default=False, description="Enable InfluxDB integration")
    influxdb_url: str = Field(default="http://localhost:8086", description="InfluxDB URL")
    influxdb_token: str = Field(default="", description="InfluxDB API Token")
    influxdb_org: str = Field(default="benchmark", description="InfluxDB Organization")
    influxdb_bucket: str = Field(default="performance", description="InfluxDB Bucket")

    @model_validator(mode="after")
    def _post_init_validation(self) -> 'BenchmarkConfig':
        self._hydrate_plugin_settings()
        if not self.plugin_settings:
            self._populate_default_plugin_settings()
        self._ensure_workloads_from_plugin_settings()
        self._validate_remote_hosts_unique() # Renamed to call the Pydantic validator
        # remote_execution handles its own path normalization via model_validator
        return self

    def ensure_output_dirs(self) -> None:
        """Ensures all configured output directories exist."""
        for path in (self.output_dir, self.report_dir, self.data_export_dir):
            path.mkdir(parents=True, exist_ok=True)

    # Pydantic's model_dump() replaces to_dict() and model_dump_json() replaces to_json()
    # No need for manual to_json or to_dict methods anymore unless custom serialization logic is complex.

    @model_validator(mode="after")
    def _validate_remote_hosts_unique(self) -> 'BenchmarkConfig':
        if not self.remote_hosts:
            return self
        names = [h.name.strip() for h in self.remote_hosts]
        if len(names) != len(set(names)):
            raise ValueError("BenchmarkConfig: remote_hosts names must be unique")
        return self

    @classmethod
    def from_json(cls, json_str: str) -> "BenchmarkConfig":
        # Use Pydantic's built-in JSON parsing and validation
        return cls.model_validate_json(json_str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkConfig":
        # Use Pydantic's built-in dictionary parsing and validation
        # Pydantic will handle nested models and Path conversions automatically
        return cls.model_validate(data)

    def save(self, filepath: Path) -> None:
        filepath.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, filepath: Path) -> "BenchmarkConfig":
        return cls.model_validate_json(filepath.read_text())

    def _hydrate_plugin_settings(self) -> None:
        """
        Convert plugin_settings dicts into their respective Pydantic models.
        This relies on the plugin registry to get the correct config_cls.
        """
        # Lazy import to avoid circular dependencies
        from lb_runner.plugin_system.builtin import builtin_plugins
        from lb_runner.plugin_system.registry import PluginRegistry

        registry = PluginRegistry(builtin_plugins())

        for name, settings_data in list(self.plugin_settings.items()): # Iterate a copy
            try:
                plugin = registry.get(name)  # Get the plugin instance
            except KeyError:
                logger.warning(
                    "Plugin '%s' not found while hydrating plugin_settings; keeping raw value.",
                    name,
                )
                continue
            if plugin and isclass(plugin.config_cls) and issubclass(plugin.config_cls, BaseModel):
                if isinstance(settings_data, dict):
                    try:
                        # Validate and convert dict to Pydantic model
                        self.plugin_settings[name] = plugin.config_cls.model_validate(settings_data)
                    except ValidationError as e:
                        logger.error(f"Validation error for plugin '{name}' config: {e}")
                        # Keep it as dict if validation fails, or remove, depending on desired strictness
                        pass
                # If it's already a Pydantic model, do nothing (or re-validate if needed)
            else:
                logger.warning(f"Plugin '{name}' not found or does not have a Pydantic config_cls. Keeping settings as dict.")

    def _ensure_workloads_from_plugin_settings(self) -> None:
        """Populate workloads dict from plugin_settings if not explicitly defined."""
        if not self.plugin_settings:
            return
        for name, settings in self.plugin_settings.items():
            if name not in self.workloads:
                # `settings` is already a Pydantic model (or a dict if _hydrate failed)
                # If it's a Pydantic model, model_dump() converts it to dict
                options_dict = settings.model_dump() if isinstance(settings, BaseModel) else settings
                self.workloads[name] = WorkloadConfig(
                    plugin=name,
                    enabled=False,
                    options=options_dict,
                )
            else:
                # Merge options from plugin_settings into workload config
                cfg = self.workloads[name]
                if not cfg.options:
                    options_dict = settings.model_dump() if isinstance(settings, BaseModel) else settings
                    cfg.options = options_dict

    def _populate_default_plugin_settings(self) -> None:
        """Fallback default plugin configs (e.g., stress_ng only for basic setup)."""
        # Lazy import to avoid circular dependencies
        from lb_runner.plugin_system.builtin import builtin_plugins
        from lb_runner.plugin_system.registry import PluginRegistry

        registry = PluginRegistry(builtin_plugins())

        for name in registry.available():
            if name in self.plugin_settings:
                continue
            try:
                plugin = registry.get(name)
            except KeyError:
                continue
            if not (plugin and isclass(plugin.config_cls) and issubclass(plugin.config_cls, BaseModel)):
                continue
            try:
                self.plugin_settings[name] = plugin.config_cls()  # Instantiate default Pydantic config
            except (ValidationError, TypeError) as exc:
                # Some plugin configs require mandatory settings (e.g., remote hosts, license keys).
                logger.debug("Skipping default config for plugin '%s': %s", name, exc)


    # Removed _normalize_playbook_paths as its logic is now within RemoteExecutionConfig's model_validator
