"""
Configuration module for Linux performance benchmarking.

This module provides centralized configuration management for all benchmark tests,
including test parameters, workload generator settings, and metric collector settings.
"""

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_TOP500_REPO = "https://github.com/geerlingguy/top500-benchmark.git"


@dataclass
class StressNGConfig:
    """Configuration for stress-ng workload generator."""
    
    cpu_workers: int = 0  # 0 means use all available CPUs
    cpu_method: str = "all"  # CPU stress method
    vm_workers: int = 1  # Virtual memory workers
    vm_bytes: str = "1G"  # Memory per VM worker
    io_workers: int = 1  # I/O workers
    timeout: int = 60  # Timeout in seconds
    metrics_brief: bool = True  # Use brief metrics output
    extra_args: List[str] = field(default_factory=list)


@dataclass
class IPerf3Config:
    """Configuration for iperf3 network testing."""
    
    server_host: str = "localhost"
    server_port: int = 5201
    protocol: str = "tcp"  # tcp or udp
    parallel: int = 1  # Number of parallel streams
    time: int = 60  # Test duration in seconds
    bandwidth: Optional[str] = None  # Target bandwidth (e.g., "1G")
    reverse: bool = False  # Reverse test direction
    json_output: bool = True


@dataclass
class DDConfig:
    """Configuration for dd I/O testing."""
    
    if_path: str = "/dev/zero"
    of_path: str = "/tmp/dd_test"
    bs: str = "1M"  # Block size
    count: int = 1024  # Number of blocks
    conv: Optional[str] = None  # Conversion options
    oflag: Optional[str] = "direct"  # Output flags


@dataclass
class FIOConfig:
    """Configuration for fio I/O testing."""
    
    job_file: Optional[Path] = None
    runtime: int = 60
    rw: str = "randrw"  # Read/write pattern
    bs: str = "4k"  # Block size
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
        "cpu-cycles",
        "instructions",
        "cache-references",
        "cache-misses",
        "branches",
        "branch-misses"
    ])
    interval_ms: int = 1000  # Sampling interval in milliseconds
    pid: Optional[int] = None  # Process ID to monitor
    cpu: Optional[int] = None  # CPU to monitor


@dataclass
class MetricCollectorConfig:
    """Configuration for metric collectors."""
    
    psutil_interval: float = 1.0  # Sampling interval in seconds
    cli_commands: List[str] = field(default_factory=lambda: [
        "sar -u 1 1",
        "vmstat 1 1",
        "iostat -d 1 1",
        "mpstat 1 1",
        "pidstat -h 1 1",
    ])
    perf_config: PerfConfig = field(default_factory=PerfConfig)
    enable_ebpf: bool = False  # eBPF requires special privileges


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
        """Render the host as an Ansible inventory line."""
        base = (
            f"{self.name} ansible_host={self.address} "
            f"ansible_port={self.port} ansible_user={self.user}"
        )
        become = ""
        if self.become:
            become = " ansible_become=true"
            if self.become_method:
                become += f" ansible_become_method={self.become_method}"
        
        extras_parts = []
        for k, v in self.vars.items():
            val_str = str(v)
            if " " in val_str or "=" in val_str:
                val_str = f'"{val_str}"'
            extras_parts.append(f" {k}={val_str}")
            
        extras = "".join(extras_parts)
        return f"{base}{become}{extras}"


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
    
    # Workload generator configurations
    stress_ng: StressNGConfig = field(default_factory=StressNGConfig)
    iperf3: IPerf3Config = field(default_factory=IPerf3Config)
    dd: DDConfig = field(default_factory=DDConfig)
    fio: FIOConfig = field(default_factory=FIOConfig)
    top500: Top500Config = field(default_factory=Top500Config)
    
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
        """Validate configuration and populate defaults."""
        if not self.workloads:
            self.workloads = self._build_default_workloads()
        self._validate_remote_hosts()

    def ensure_output_dirs(self) -> None:
        """Ensure output, report, and export directories exist."""
        for path in (self.output_dir, self.report_dir, self.data_export_dir):
            path.mkdir(parents=True, exist_ok=True)
    
    def to_json(self) -> str:
        """Convert configuration to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
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
        """Ensure remote hosts use non-empty, unique names for per-host outputs."""
        if not self.remote_hosts:
            return

        names: List[str] = []
        for host in self.remote_hosts:
            name = host.name.strip() if host.name is not None else ""
            if not name:
                raise ValueError("remote_hosts entries must have a non-empty name.")
            names.append(name)

        counter = Counter(names)
        duplicates = [name for name, count in counter.items() if count > 1]
        if duplicates:
            dup_list = ", ".join(sorted(duplicates))
            raise ValueError(
                f"remote_hosts names must be unique; duplicates: {dup_list}."
            )
    
    @classmethod
    def from_json(cls, json_str: str) -> "BenchmarkConfig":
        """Create configuration from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkConfig":
        """Create configuration from dictionary."""
        # Convert nested dictionaries to dataclass instances
        if "stress_ng" in data:
            data["stress_ng"] = StressNGConfig(**data["stress_ng"])
        if "iperf3" in data:
            data["iperf3"] = IPerf3Config(**data["iperf3"])
        if "dd" in data:
            data["dd"] = DDConfig(**data["dd"])
        if "fio" in data:
            data["fio"] = FIOConfig(**data["fio"])
        if "collectors" in data:
            if "perf_config" in data["collectors"]:
                data["collectors"]["perf_config"] = PerfConfig(**data["collectors"]["perf_config"])
            data["collectors"] = MetricCollectorConfig(**data["collectors"])
        if "top500" in data:
            if "workdir" in data["top500"] and isinstance(data["top500"]["workdir"], str):
                data["top500"]["workdir"] = Path(data["top500"]["workdir"])
            data["top500"] = Top500Config(**data["top500"])
        if "remote_hosts" in data:
            data["remote_hosts"] = [
                RemoteHostConfig(**host_cfg) for host_cfg in data["remote_hosts"]
            ]
        if "remote_execution" in data:
            remote_exec = data["remote_execution"]
            if "inventory_path" in remote_exec and isinstance(remote_exec["inventory_path"], str):
                remote_exec["inventory_path"] = Path(remote_exec["inventory_path"])
            for key in ["setup_playbook", "run_playbook", "collect_playbook"]:
                if key in remote_exec and isinstance(remote_exec[key], str):
                    remote_exec[key] = Path(remote_exec[key])
            data["remote_execution"] = RemoteExecutionConfig(**remote_exec)
        
        # Convert string paths to Path objects
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
        
        return cls(**data)
    
    def save(self, filepath: Path) -> None:
        """Save configuration to file."""
        with open(filepath, "w") as f:
            f.write(self.to_json())
    
    @classmethod
    def load(cls, filepath: Path) -> "BenchmarkConfig":
        """Load configuration from file."""
        with open(filepath, "r") as f:
            return cls.from_json(f.read())

    def _build_default_workloads(self) -> Dict[str, "WorkloadConfig"]:
        """Create workload entries from legacy config fields."""
        return {
            "stress_ng": WorkloadConfig(
                plugin="stress_ng",
                enabled=True,
                options=asdict(self.stress_ng),
            ),
            "iperf3": WorkloadConfig(
                plugin="iperf3",
                enabled=True,
                options=asdict(self.iperf3),
            ),
            "dd": WorkloadConfig(
                plugin="dd",
                enabled=True,
                options=asdict(self.dd),
            ),
            "fio": WorkloadConfig(
                plugin="fio",
                enabled=True,
                options=asdict(self.fio),
            ),
            "top500": WorkloadConfig(
                plugin="top500",
                enabled=False,
                options=asdict(self.top500),
            ),
        }
