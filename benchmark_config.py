"""
Configuration module for Linux performance benchmarking.

This module provides centralized configuration management.
"""

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class StressNGConfig:
    """Compatibility config for stress-ng (matches workload_generators version)."""

    cpu_workers: int = 0  # 0 means use all available CPUs
    cpu_method: str = "all"  # CPU stress method
    vm_workers: int = 1  # Virtual memory workers
    vm_bytes: str = "1G"  # Memory per VM worker
    io_workers: int = 1  # I/O workers
    timeout: int = 60  # Timeout in seconds
    metrics_brief: bool = True  # Use brief metrics output
    extra_args: List[str] = field(default_factory=list)

DEFAULT_TOP500_REPO = "https://github.com/geerlingguy/top500-benchmark.git"

# Legacy configs kept here until all plugins are refactored
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

@dataclass
class DDConfig:
    """Configuration for dd I/O testing."""
    if_path: str = "/dev/zero"
    of_path: str = "/tmp/dd_test"
    bs: str = "1M"
    count: int = 1024
    conv: Optional[str] = None
    oflag: Optional[str] = "direct"

@dataclass
class FIOConfig:
    """Configuration for fio I/O testing."""
    job_file: Optional[Path] = None
    runtime: int = 60
    rw: str = "randrw"
    bs: str = "4k"
    iodepth: int = 16
    numjobs: int = 1
    size: str = "1G"
    directory: str = "/tmp"
    name: str = "benchmark"
    output_format: str = "json"

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
class Top500Config:
    """Configuration for the Top500 (HPL Linpack) workload plugin."""
    repo_url: str = DEFAULT_TOP500_REPO
    repo_ref: Optional[str] = None
    workdir: Path = Path("/opt/top500-benchmark")
    tags: List[str] = field(default_factory=lambda: ["setup", "benchmark"])
    inventory_hosts: List[str] = field(default_factory=lambda: ["localhost ansible_connection=local"])
    config_overrides: Dict[str, Any] = field(default_factory=dict)

@dataclass
class WorkloadConfig:
    """Configuration wrapper for workload plugins."""
    plugin: str
    enabled: bool = True
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
    
    # Legacy hardcoded fields (temporarily kept for non-migrated plugins)
    stress_ng: StressNGConfig = field(default_factory=StressNGConfig)
    iperf3: IPerf3Config = field(default_factory=IPerf3Config)
    dd: DDConfig = field(default_factory=DDConfig)
    fio: FIOConfig = field(default_factory=FIOConfig)
    top500: Top500Config = field(default_factory=Top500Config)
    
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
        if self.stress_ng and "stress_ng" not in self.plugin_settings:
            self.plugin_settings["stress_ng"] = self.stress_ng
        self._hydrate_plugin_settings()
        if not self.workloads:
            self.workloads = self._build_default_workloads()
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
        
        # Handle legacy fields
        if "iperf3" in data: data["iperf3"] = IPerf3Config(**data["iperf3"])
        if "dd" in data: data["dd"] = DDConfig(**data["dd"])
        if "fio" in data: data["fio"] = FIOConfig(**data["fio"])
        if "top500" in data:
            if "workdir" in data["top500"]: data["top500"]["workdir"] = Path(data["top500"]["workdir"])
            data["top500"] = Top500Config(**data["top500"])

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
        
        # Also preserve any existing plugin_settings
        if "plugin_settings" in data:
            plugin_settings.update(data.pop("plugin_settings"))
            
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
            from workload_generators.stress_ng_generator import StressNGConfig
            _convert("stress_ng", StressNGConfig)
        except Exception:
            pass

        try:
            from workload_generators.geekbench_generator import GeekbenchConfig
            _convert("geekbench", GeekbenchConfig)
        except Exception:
            pass

        try:
            from workload_generators.sysbench_generator import SysbenchConfig
            if "sysbench" in self.plugin_settings and isinstance(self.plugin_settings["sysbench"], dict):
                if self.plugin_settings["sysbench"].get("events") is None:
                    self.plugin_settings["sysbench"]["events"] = 0
            _convert("sysbench", SysbenchConfig)
        except Exception:
            pass

    def _build_default_workloads(self) -> Dict[str, "WorkloadConfig"]:
        # Helper to build defaults. 
        # Note: For migrated plugins, we need to check plugin_settings or use defaults.
        # This is where the coupling was. We should ideally ask the registry.
        # For now, we just replicate the structure.
        
        defaults = {
            "iperf3": WorkloadConfig("iperf3", True, asdict(self.iperf3)),
            "dd": WorkloadConfig("dd", True, asdict(self.dd)),
            "fio": WorkloadConfig("fio", True, asdict(self.fio)),
            "top500": WorkloadConfig("top500", False, asdict(self.top500)),
        }

        def _add_plugin_default(name: str, config_cls: Any, enabled: bool) -> None:
            existing = self.plugin_settings.get(name, {})
            try:
                if isinstance(existing, config_cls):
                    cfg_obj = existing
                elif isinstance(existing, dict):
                    cfg_obj = config_cls(**existing)
                elif hasattr(existing, "__dict__"):
                    cfg_obj = config_cls(**asdict(existing))
                else:
                    cfg_obj = config_cls()
                # Persist hydrated config for downstream services
                self.plugin_settings[name] = cfg_obj
                defaults[name] = WorkloadConfig(name, enabled, asdict(cfg_obj))
            except Exception:
                defaults[name] = WorkloadConfig(name, enabled, existing or {})

        try:
            from workload_generators.stress_ng_generator import StressNGConfig
            _add_plugin_default("stress_ng", StressNGConfig, True)
        except Exception:
            defaults.setdefault("stress_ng", WorkloadConfig("stress_ng", True, {}))

        try:
            from workload_generators.geekbench_generator import GeekbenchConfig
            _add_plugin_default("geekbench", GeekbenchConfig, False)
        except Exception:
            defaults.setdefault("geekbench", WorkloadConfig("geekbench", False, {}))

        try:
            from workload_generators.sysbench_generator import SysbenchConfig
            _add_plugin_default("sysbench", SysbenchConfig, False)
        except Exception:
            defaults.setdefault("sysbench", WorkloadConfig("sysbench", False, {}))

        return defaults
