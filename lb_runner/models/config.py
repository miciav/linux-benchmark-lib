"""Benchmark configuration (canonical runner/controller definition)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lb_common.api import (
    parse_bool_env,
    parse_float_env,
    parse_int_env,
    parse_labels_env,
)
from lb_plugins.api import PluginAssetConfig

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


DEFAULT_LB_WORKDIR = (
    "{{ (ansible_user == 'root') | ternary('/root', '/home/' ~ ansible_user) }}/.lb"
)


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


class LokiConfig(BaseModel):
    """Configuration for Loki log shipping."""

    enabled: bool = Field(default=False, description="Enable Loki log push")
    endpoint: str = Field(
        default="http://localhost:3100",
        description="Loki base URL or push endpoint",
    )
    labels: Dict[str, str] = Field(
        default_factory=dict, description="Static labels sent with Loki logs"
    )
    batch_size: int = Field(default=100, gt=0, description="Logs per batch")
    flush_interval_ms: int = Field(
        default=1000, gt=0, description="Flush interval in milliseconds"
    )
    timeout_seconds: float = Field(
        default=5.0, gt=0, description="HTTP timeout for Loki push"
    )
    max_retries: int = Field(default=3, ge=0, description="Max retries on failure")
    max_queue_size: int = Field(
        default=10000, gt=0, description="Max pending logs in queue"
    )
    backoff_base: float = Field(
        default=0.5, ge=0, description="Base backoff delay in seconds"
    )
    backoff_factor: float = Field(
        default=2.0, ge=1.0, description="Backoff multiplier"
    )

    @model_validator(mode="before")
    @classmethod
    def _apply_env_fallbacks(cls, values: Any) -> Any:
        """Apply environment variables as fallbacks for missing config values.

        Priority: config file > environment variables > field defaults.
        Environment variables are only used when the config file doesn't
        provide a value (None or missing key).
        """
        if isinstance(values, cls):
            return values
        if not isinstance(values, dict):
            return values

        # Only apply env vars as fallbacks when config doesn't specify a value
        if values.get("enabled") is None:
            env_enabled = parse_bool_env(os.environ.get("LB_LOKI_ENABLED"))
            if env_enabled is not None:
                values["enabled"] = env_enabled

        if not values.get("endpoint"):
            env_endpoint = os.environ.get("LB_LOKI_ENDPOINT")
            if env_endpoint:
                values["endpoint"] = env_endpoint

        # For labels, merge env labels with config labels (config takes precedence)
        env_labels = parse_labels_env(os.environ.get("LB_LOKI_LABELS"))
        if env_labels:
            merged = dict(env_labels)  # Start with env labels
            merged.update(values.get("labels") or {})  # Config overwrites env
            values["labels"] = merged

        if values.get("batch_size") is None:
            env_batch_size = parse_int_env(os.environ.get("LB_LOKI_BATCH_SIZE"))
            if env_batch_size is not None:
                values["batch_size"] = env_batch_size

        if values.get("flush_interval_ms") is None:
            env_flush_ms = parse_int_env(os.environ.get("LB_LOKI_FLUSH_INTERVAL_MS"))
            if env_flush_ms is not None:
                values["flush_interval_ms"] = env_flush_ms

        if values.get("timeout_seconds") is None:
            env_timeout = parse_float_env(os.environ.get("LB_LOKI_TIMEOUT_SECONDS"))
            if env_timeout is not None:
                values["timeout_seconds"] = env_timeout

        if values.get("max_retries") is None:
            env_retries = parse_int_env(os.environ.get("LB_LOKI_MAX_RETRIES"))
            if env_retries is not None:
                values["max_retries"] = env_retries

        if values.get("max_queue_size") is None:
            env_queue = parse_int_env(os.environ.get("LB_LOKI_MAX_QUEUE_SIZE"))
            if env_queue is not None:
                values["max_queue_size"] = env_queue

        if values.get("backoff_base") is None:
            env_backoff_base = parse_float_env(os.environ.get("LB_LOKI_BACKOFF_BASE"))
            if env_backoff_base is not None:
                values["backoff_base"] = env_backoff_base

        if values.get("backoff_factor") is None:
            env_backoff_factor = parse_float_env(os.environ.get("LB_LOKI_BACKOFF_FACTOR"))
            if env_backoff_factor is not None:
                values["backoff_factor"] = env_backoff_factor

        return values


class GrafanaPlatformConfig(BaseModel):
    """Platform-level Grafana connection settings."""

    url: str = Field(default="http://localhost:3000", description="Grafana base URL")
    api_key: str | None = Field(default=None, description="Grafana API key (optional)")
    org_id: int = Field(default=1, ge=1, description="Grafana organization id")

    model_config = {"extra": "ignore"}


class RemoteHostConfig(BaseModel):
    """Configuration for a remote benchmark host."""

    model_config = ConfigDict(extra="ignore")

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

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=False, description="Enable remote execution")
    inventory_path: Optional[Path] = Field(default=None, description="Path to a custom Ansible inventory file")
    lb_workdir: str = Field(
        default=DEFAULT_LB_WORKDIR,
        description="Remote workdir for benchmark install (Ansible-templated)",
    )
    run_setup: bool = Field(default=True, description="Execute setup playbooks before tests")
    run_collect: bool = Field(default=True, description="Execute collection playbooks after tests")
    setup_playbook: Optional[Path] = Field(default=None, description="Path to the Ansible setup playbook")
    run_playbook: Optional[Path] = Field(default=None, description="Path to the Ansible run playbook")
    collect_playbook: Optional[Path] = Field(default=None, description="Path to the Ansible collect playbook")
    teardown_playbook: Optional[Path] = Field(default=None, description="Path to the Ansible teardown playbook")
    run_teardown: bool = Field(default=True, description="Execute teardown playbooks after tests")
    upgrade_pip: bool = Field(default=False, description="Upgrade pip inside the benchmark virtual environment during setup")
    use_container_fallback: bool = Field(default=False, description="Use container-based fallback for remote execution")


class WorkloadConfig(BaseModel):
    """Configuration wrapper for workload plugins."""

    model_config = ConfigDict(extra="ignore")

    plugin: str = Field(description="Name of the plugin to use")
    enabled: bool = Field(default=True, description="Whether this workload is enabled")
    intensity: str = Field(default="user_defined", description="Pre-defined intensity level (low, medium, high, user_defined)")
    options: Dict[str, Any] = Field(default_factory=dict, description="Plugin-specific options for the workload")


class BenchmarkConfig(BaseModel):
    """Main configuration for benchmark tests."""

    model_config = ConfigDict(extra="ignore")

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
    plugin_assets: Dict[str, PluginAssetConfig] = Field(
        default_factory=dict,
        description="Resolved plugin Ansible assets/extravars (from runner registry)",
    )

    # Metric collector configuration
    collectors: MetricCollectorConfig = Field(default_factory=MetricCollectorConfig, description="Configuration for metric collectors")

    # Workload plugin configuration (name -> WorkloadConfig)
    workloads: Dict[str, WorkloadConfig] = Field(default_factory=dict, description="Dictionary of workload definitions")

    # Remote execution configuration
    remote_hosts: List[RemoteHostConfig] = Field(default_factory=list, description="List of remote hosts for benchmarking")
    remote_execution: RemoteExecutionConfig = Field(default_factory=RemoteExecutionConfig, description="Configuration for remote execution")

    # System information collection
    collect_system_info: bool = Field(default=True, description="Collect system information before running benchmarks")

    # Loki configuration (optional)
    loki: LokiConfig = Field(
        default_factory=LokiConfig, description="Loki log shipping configuration"
    )

    # InfluxDB configuration (optional)
    influxdb_enabled: bool = Field(default=False, description="Enable InfluxDB integration")
    influxdb_url: str = Field(default="http://localhost:8086", description="InfluxDB URL")
    influxdb_token: str = Field(default="", description="InfluxDB API Token")
    influxdb_org: str = Field(default="benchmark", description="InfluxDB Organization")
    influxdb_bucket: str = Field(default="performance", description="InfluxDB Bucket")

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

    # Removed _normalize_playbook_paths as its logic is now within RemoteExecutionConfig's model_validator


class PlatformConfig(BaseModel):
    """Platform-level configuration for defaults and plugin enablement."""

    model_config = ConfigDict(extra="ignore")

    plugins: Dict[str, bool] = Field(
        default_factory=dict,
        description="Plugin enable/disable map (missing entries default to enabled)",
    )
    output_dir: Optional[Path] = Field(
        default=None, description="Default benchmark output directory"
    )
    report_dir: Optional[Path] = Field(
        default=None, description="Default report directory"
    )
    data_export_dir: Optional[Path] = Field(
        default=None, description="Default data export directory"
    )
    loki: Optional[LokiConfig] = Field(
        default=None, description="Optional Loki defaults for the platform"
    )
    grafana: Optional[GrafanaPlatformConfig] = Field(
        default=None, description="Optional Grafana defaults for the platform"
    )

    def is_plugin_enabled(self, name: str) -> bool:
        """Return True when the plugin is enabled or not explicitly disabled."""
        return self.plugins.get(name, True)

    def save(self, filepath: Path) -> None:
        filepath.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, filepath: Path) -> "PlatformConfig":
        return cls.model_validate_json(filepath.read_text())
