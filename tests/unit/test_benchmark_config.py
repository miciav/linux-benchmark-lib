"""
Unit tests for the benchmark_config module.
"""

import pytest
import json
from pathlib import Path
import tempfile

from benchmark_config import (
    BenchmarkConfig,
    StressNGConfig,
    IPerf3Config,
    DDConfig,
    FIOConfig,
    MetricCollectorConfig,
    PerfConfig,
    RemoteHostConfig,
    WorkloadConfig,
)


class TestBenchmarkConfig:
    """Test cases for BenchmarkConfig class."""
    
    def test_default_config_creation(self):
        """Test creating a config with default values."""
        config = BenchmarkConfig()
        
        assert config.repetitions == 3
        assert config.test_duration_seconds == 60
        assert config.metrics_interval_seconds == 1.0
        assert isinstance(config.stress_ng, StressNGConfig)
        assert isinstance(config.iperf3, IPerf3Config)
        assert isinstance(config.dd, DDConfig)
        assert isinstance(config.fio, FIOConfig)
        assert "stress_ng" in config.workloads
        assert config.workloads["stress_ng"].plugin == "stress_ng"
        
    def test_custom_config_creation(self):
        """Test creating a config with custom values."""
        config = BenchmarkConfig(
            repetitions=5,
            test_duration_seconds=120,
            stress_ng=StressNGConfig(cpu_workers=4)
        )
        
        assert config.repetitions == 5
        assert config.test_duration_seconds == 120
        assert config.stress_ng.cpu_workers == 4
        assert config.workloads["stress_ng"].options["cpu_workers"] == 4
        
    def test_config_directories_creation(self):
        """Test that output directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = BenchmarkConfig(
                output_dir=Path(tmpdir) / "output",
                report_dir=Path(tmpdir) / "reports",
                data_export_dir=Path(tmpdir) / "exports"
            )
            
            assert config.output_dir.exists()
            assert config.report_dir.exists()
            assert config.data_export_dir.exists()
            
    def test_config_to_json(self):
        """Test converting config to JSON."""
        config = BenchmarkConfig(repetitions=7)
        json_str = config.to_json()
        
        data = json.loads(json_str)
        assert data["repetitions"] == 7
        assert "stress_ng" in data
        assert "collectors" in data
        assert "workloads" in data
        
    def test_config_save_load(self):
        """Test saving and loading config."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_path = Path(f.name)
            
        try:
            # Create and save config
            config = BenchmarkConfig(
                repetitions=10,
                test_duration_seconds=90,
                stress_ng=StressNGConfig(cpu_workers=8)
            )
            config.save(config_path)
            
            # Load config
            loaded_config = BenchmarkConfig.load(config_path)
            
            assert loaded_config.repetitions == 10
            assert loaded_config.test_duration_seconds == 90
            assert loaded_config.stress_ng.cpu_workers == 8
            assert loaded_config.workloads["stress_ng"].options["cpu_workers"] == 8
            
        finally:
            config_path.unlink()

    def test_remote_hosts_require_name(self):
        """Remote hosts must have a non-empty name."""
        with pytest.raises(ValueError):
            BenchmarkConfig(
                remote_hosts=[
                    RemoteHostConfig(name="   ", address="192.168.0.1"),
                ]
            )

    def test_remote_hosts_names_unique(self):
        """Remote host names must be unique."""
        host_a = RemoteHostConfig(name="node1", address="10.0.0.1")
        host_b = RemoteHostConfig(name="node1", address="10.0.0.2")
        with pytest.raises(ValueError):
            BenchmarkConfig(remote_hosts=[host_a, host_b])

    def test_module_does_not_create_default_instance(self):
        """The module should not instantiate configs at import time."""
        import benchmark_config as bc

        assert not hasattr(bc, "default_config")

    def test_workloads_use_single_config_class(self):
        """Ensure workloads are instances of the declared WorkloadConfig."""
        config = BenchmarkConfig()
        assert all(isinstance(wl, WorkloadConfig) for wl in config.workloads.values())

        round_trip = BenchmarkConfig.from_dict(config.to_dict())
        assert all(isinstance(wl, WorkloadConfig) for wl in round_trip.workloads.values())


class TestStressNGConfig:
    """Test cases for StressNGConfig class."""
    
    def test_default_values(self):
        """Test default StressNGConfig values."""
        config = StressNGConfig()
        
        assert config.cpu_workers == 0
        assert config.cpu_method == "all"
        assert config.vm_workers == 1
        assert config.vm_bytes == "1G"
        assert config.timeout == 60
        
    def test_custom_values(self):
        """Test custom StressNGConfig values."""
        config = StressNGConfig(
            cpu_workers=4,
            cpu_method="matrixprod",
            vm_bytes="2G",
            extra_args=["--verbose"]
        )
        
        assert config.cpu_workers == 4
        assert config.cpu_method == "matrixprod"
        assert config.vm_bytes == "2G"
        assert "--verbose" in config.extra_args


class TestIPerf3Config:
    """Test cases for IPerf3Config class."""
    
    def test_default_values(self):
        """Test default IPerf3Config values."""
        config = IPerf3Config()
        
        assert config.server_host == "localhost"
        assert config.server_port == 5201
        assert config.protocol == "tcp"
        assert config.parallel == 1
        assert config.time == 60
        
    def test_custom_values(self):
        """Test custom IPerf3Config values."""
        config = IPerf3Config(
            server_host="192.168.1.100",
            protocol="udp",
            parallel=4,
            bandwidth="100M"
        )
        
        assert config.server_host == "192.168.1.100"
        assert config.protocol == "udp"
        assert config.parallel == 4
        assert config.bandwidth == "100M"


class TestPerfConfig:
    """Test cases for PerfConfig class."""
    
    def test_default_events(self):
        """Test default perf events."""
        config = PerfConfig()
        
        assert "cpu-cycles" in config.events
        assert "instructions" in config.events
        assert "cache-misses" in config.events
        assert config.interval_ms == 1000
        
    def test_custom_events(self):
        """Test custom perf events."""
        custom_events = ["cpu-clock", "page-faults"]
        config = PerfConfig(events=custom_events, interval_ms=500)
        
        assert config.events == custom_events
        assert config.interval_ms == 500
