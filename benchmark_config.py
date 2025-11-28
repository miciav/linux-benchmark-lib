"""
Configuration module for Linux performance benchmarking.

This module provides centralized configuration management.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PerfConfig:
    """Configuration for perf profiling."""
    events: List[str] = field(default_factory=lambda: [
        "cpu-cycles", "instructions", "cache-references",
        "cache-misses", "branches", "branch-misses"
    ])
    interval_ms: int = 1000
    pid: Optional[int] = None
    cpu: Optional[int] = None

@dataclass
class MetricCollectorConfig:
    """Configuration for metric collectors."""
    psutil_interval: float = 1.0
    cli_commands: List[str] = field(default_factory=lambda: [
        "sar -u 1 1", "vmstat 1 1", "iostat -d 1 1",
        "mpstat 1 1", "pidstat -h 1 1",
    ])
    perf_config: PerfConfig = field(default_factory=PerfConfig)
    enable_ebpf: bool = False

@dataclass
class RemoteHostConfig:
    """Configuration for a remote benchmark host."""
    name: str = "localhost"
    address: str = "127.0.0.1"
    port: int = 22
    user: str = "root"
    become: bool = True
    become_method: str = "sudo"
    vars: Dict[str, Any] = field(default_factory=dict)

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
                val = f"\"{val}\""
            parts.append(f"{key}={val}")
        return " ".join(parts)

@dataclass
class RemoteExecutionConfig:
    """Configuration for remote execution via Ansible."""
    enabled: bool = False
    inventory_path: Optional[Path] = None
    run_setup: bool = True
    run_collect: bool = True
    setup_playbook: Path = Path("ansible/playbooks/setup.yml")
    run_playbook: Path = Path("ansible/playbooks/run_benchmark.yml")
    collect_playbook: Path = Path("ansible/playbooks/collect.yml")
    use_container_fallback: bool = False

@dataclass
class WorkloadConfig:
    """Configuration wrapper for workload plugins."""
    plugin: str
    enabled: bool = True
    intensity: str = "user_defined"  # low, medium, high, user_defined
    options: Dict[str, Any] = field(default_factory=dict)

@dataclass
class BenchmarkConfig:
    """Main configuration for benchmark tests."""
    
    # Test execution parameters
    repetitions: int = 3
    test_duration_seconds: int = 60
    metrics_interval_seconds: float = 1.0
    warmup_seconds: int = 5
    cooldown_seconds: int = 5
    
    # Output configuration
    output_dir: Path = Path("./benchmark_results")
    report_dir: Path = Path("./reports")
    data_export_dir: Path = Path("./data_exports")
    
    # Dynamic Plugin Settings (The new way)
    # Stores config objects for migrated plugins (stress_ng, geekbench)
    plugin_settings: Dict[str, Any] = field(default_factory=dict)

    # Metric collector configuration
    collectors: MetricCollectorConfig = field(default_factory=MetricCollectorConfig)

    # Workload plugin configuration (name -> config)
    workloads: Dict[str, WorkloadConfig] = field(default_factory=dict)

    # Remote execution configuration
    remote_hosts: List[RemoteHostConfig] = field(default_factory=list)
    remote_execution: RemoteExecutionConfig = field(default_factory=RemoteExecutionConfig)
    
    # System information collection
    collect_system_info: bool = True
    
    # InfluxDB configuration (optional)
    influxdb_enabled: bool = False
    influxdb_url: str = "http://localhost:8086"
    influxdb_token: str = ""
    influxdb_org: str = "benchmark"
    influxdb_bucket: str = "performance"
    
    def __post_init__(self) -> None:
        self._hydrate_plugin_settings()
        self._ensure_workloads_from_plugin_settings()
        self._validate_remote_hosts()

    def ensure_output_dirs(self) -> None:
        for path in (self.output_dir, self.report_dir, self.data_export_dir):
            path.mkdir(parents=True, exist_ok=True)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    def to_dict(self) -> Dict[str, Any]:
        def _convert(obj: Any) -> Any:
            if hasattr(obj, "__dict__"):
                return {k: _convert(v) for k, v in obj.__dict__.items()}
            elif isinstance(obj, Path):
                return str(obj)
            elif isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_convert(item) for item in obj]
            else:
                return obj
        return _convert(self)

    def _validate_remote_hosts(self) -> None:
        if not self.remote_hosts:
            return
        for host in self.remote_hosts:
            if not host.name or not host.name.strip():
                raise ValueError("remote_hosts names must be non-empty")
        names = [h.name.strip() for h in self.remote_hosts]
        if len(names) != len(set(names)):
            raise ValueError("remote_hosts names must be unique")
    
    @classmethod
    def from_json(cls, json_str: str) -> "BenchmarkConfig":
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkConfig":
        # We need to handle this in ConfigService mainly, but for basic usage:

        # Handle migrated fields (stress_ng, geekbench) that might still be in the JSON root
        # We move them to plugin_settings temporarily as dicts.
        # The ConfigService will upgrade them to Objects later.
        plugin_settings = {}
        if "stress_ng" in data:
            plugin_settings["stress_ng"] = data.pop("stress_ng")
        if "geekbench" in data:
            plugin_settings["geekbench"] = data.pop("geekbench")
        if "sysbench" in data:
            plugin_settings["sysbench"] = data.pop("sysbench")
        for legacy_plugin in ["iperf3", "dd", "fio", "top500"]:
            if legacy_plugin in data:
                plugin_settings[legacy_plugin] = data.pop(legacy_plugin)
        
        # Also preserve any existing plugin_settings
        if "plugin_settings" in data:
            plugin_settings.update(data.pop("plugin_settings"))

        # Normalize path-like entries for known plugins
        if "top500" in plugin_settings and isinstance(plugin_settings["top500"], dict):
            if "workdir" in plugin_settings["top500"] and isinstance(plugin_settings["top500"]["workdir"], str):
                plugin_settings["top500"]["workdir"] = Path(plugin_settings["top500"]["workdir"])
        if "fio" in plugin_settings and isinstance(plugin_settings["fio"], dict):
            if "job_file" in plugin_settings["fio"] and isinstance(plugin_settings["fio"]["job_file"], str):
                plugin_settings["fio"]["job_file"] = Path(plugin_settings["fio"]["job_file"])
            
        if "collectors" in data:
            if "perf_config" in data["collectors"]:
                data["collectors"]["perf_config"] = PerfConfig(**data["collectors"]["perf_config"])
            data["collectors"] = MetricCollectorConfig(**data["collectors"])
            
        if "remote_hosts" in data:
            data["remote_hosts"] = [RemoteHostConfig(**h) for h in data["remote_hosts"]]
            
        if "remote_execution" in data:
            # Path conversion logic...
            remote_exec = data["remote_execution"]
            if "inventory_path" in remote_exec and isinstance(remote_exec["inventory_path"], str):
                remote_exec["inventory_path"] = Path(remote_exec["inventory_path"])
            for key in ["setup_playbook", "run_playbook", "collect_playbook"]:
                if key in remote_exec and isinstance(remote_exec[key], str):
                    remote_exec[key] = Path(remote_exec[key])
            data["remote_execution"] = RemoteExecutionConfig(**remote_exec)

        for key in ["output_dir", "report_dir", "data_export_dir"]:
            if key in data and isinstance(data[key], str):
                data[key] = Path(data[key])

        if "workloads" in data:
            data["workloads"] = {
                name: WorkloadConfig(
                    plugin=cfg.get("plugin", name),
                    enabled=cfg.get("enabled", True),
                    intensity=cfg.get("intensity", "user_defined"),
                    options=cfg.get("options", {}),
                )
                for name, cfg in data["workloads"].items()
            }

        data["plugin_settings"] = plugin_settings
        return cls(**data)
    
    def save(self, filepath: Path) -> None:
        with open(filepath, "w") as f:
            f.write(self.to_json())
    
    @classmethod
    def load(cls, filepath: Path) -> "BenchmarkConfig":
        with open(filepath, "r") as f:
            return cls.from_json(f.read())

    def _hydrate_plugin_settings(self) -> None:
        """Convert stored plugin_settings dicts to typed config objects when possible."""

        def _convert(name: str, config_cls: Any) -> None:
            if name in self.plugin_settings and isinstance(self.plugin_settings[name], dict):
                try:
                    self.plugin_settings[name] = config_cls(**self.plugin_settings[name])
                except Exception:
                    # Leave as dict if instantiation fails
                    pass

        try:
            from plugins.stress_ng.plugin import StressNGConfig
            _convert("stress_ng", StressNGConfig)
        except Exception:
            pass

        try:
            from plugins.iperf3.plugin import IPerf3Config
            _convert("iperf3", IPerf3Config)
        except Exception:
            pass

        try:
            from plugins.fio.plugin import FIOConfig
            _convert("fio", FIOConfig)
        except Exception:
            pass

        try:
            from plugins.dd.plugin import DDConfig
            _convert("dd", DDConfig)
        except Exception:
            pass

    def _ensure_workloads_from_plugin_settings(self) -> None:
        """
        Ensure every plugin setting has a corresponding WorkloadConfig entry.

        Defaults to disabled to avoid surprising runs, but captures options.
        """
        for plugin_name, settings in self.plugin_settings.items():
            if plugin_name in self.workloads:
                continue

            options: Dict[str, Any] = {}
            if hasattr(settings, "__dataclass_fields__"):
                try:
                    options = asdict(settings)
                except Exception:
                    options = {}
            elif isinstance(settings, dict):
                options = settings

            self.workloads[plugin_name] = WorkloadConfig(
                plugin=plugin_name,
                enabled=False,
                options=options,
            )
