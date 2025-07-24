"""
Configuration module for Linux performance benchmarking.

This module provides centralized configuration management for all benchmark tests,
including test parameters, workload generator settings, and metric collector settings.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
import json


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
        "sar", "vmstat", "iostat", "mpstat", "pidstat"
    ])
    perf_config: PerfConfig = field(default_factory=PerfConfig)
    enable_ebpf: bool = False  # eBPF requires special privileges
    
    
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
    
    # Metric collector configuration
    collectors: MetricCollectorConfig = field(default_factory=MetricCollectorConfig)
    
    # System information collection
    collect_system_info: bool = True
    
    # InfluxDB configuration (optional)
    influxdb_enabled: bool = False
    influxdb_url: str = "http://localhost:8086"
    influxdb_token: str = ""
    influxdb_org: str = "benchmark"
    influxdb_bucket: str = "performance"
    
    def __post_init__(self) -> None:
        """Create output directories if they don't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.data_export_dir.mkdir(parents=True, exist_ok=True)
    
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
            elif isinstance(obj, list):
                return [_convert(item) for item in obj]
            else:
                return obj
        
        return _convert(self)
    
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
        
        # Convert string paths to Path objects
        for key in ["output_dir", "report_dir", "data_export_dir"]:
            if key in data and isinstance(data[key], str):
                data[key] = Path(data[key])
        
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


# Default configuration instance
default_config = BenchmarkConfig()
