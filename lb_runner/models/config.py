"""Benchmark configuration (canonical runner/controller definition)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

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
