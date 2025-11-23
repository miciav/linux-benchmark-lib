# Linux Benchmark Library

A robust, configurable Python library for benchmarking Linux compute nodes.

## Overview

Run repeatable workloads and collect detailed system metrics under synthetic load. The library helps you understand performance variability across repetitions and workloads.

## Key Features

- **Multi-level metrics**: PSUtil, Linux CLI tools, perf events, optional eBPF
- **Plugin workloads**: stress-ng, iperf3, dd, fio shipped as plugins, extensible via entry points
- **Data aggregation**: Pandas DataFrames with metrics as index, repetitions as columns
- **Reporting**: Text reports and plots
- **Centralized config**: Typed dataclasses for all knobs
- **Remote execution**: Python controller + Ansible Runner targeting remote hosts or `localhost`

## Requirements

- Python 3.13+
- Linux for full functionality
- Root privileges for some features (perf, eBPF)

### Python Dependencies

```bash
psutil>=5.9.0
pandas>=2.0.0
numpy>=1.24.0
matplotlib>=3.7.0
seaborn>=0.12.0
iperf3>=0.1.11
performance>=0.3.0
jc>=1.23.0
influxdb-client>=1.36.0   # opzionale, usato solo per esportare su InfluxDB
```

### Required External Software

- **sysstat**: sar, vmstat, iostat, mpstat, pidstat
- **stress-ng**: load generator
- **iperf3**: network testing
- **fio**: advanced I/O testing
- **perf**: Linux profiling
- **bcc/eBPF tools**: optional kernel-level metrics

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd linux-benchmark-lib
```

2. Install with uv:
```bash
uv venv
uv pip install -e .
```

Tip: if you want the `lb` CLI available globally without activating the venv,
you can install it as a user tool:
```bash
uv tool install -e .
```

### CLI (lb)

See `CLI.md` for the full command reference. Highlights:
- Config and defaults: `lb config init`, `lb config set-default`, `lb config edit`, `lb config workloads`, `lb plugins --enable/--disable NAME` (shows enabled state with checkmarks).
- Discovery and run: `lb plugins`, `lb hosts`, `lb run [tests...]` (follows config for local/remote unless overridden).
- Health checks: `lb doctor controller`, `lb doctor local-tools`, `lb doctor multipass`, `lb doctor all`.
- Integration helper: `lb test multipass` (artifacts to `tests/results` by default).

3. Install development dependencies:
```bash
uv pip install -e ".[dev]"
```

## Quick Start

```python
from benchmark_config import BenchmarkConfig
from local_runner import LocalRunner
from orchestrator import BenchmarkOrchestrator
from benchmark_config import RemoteHostConfig, RemoteExecutionConfig

# Create a configuration
config = BenchmarkConfig(
    repetitions=3,
    test_duration_seconds=60,
    metrics_interval_seconds=1.0
)

# Local execution (no Ansible)
runner = LocalRunner(config)
runner.run_benchmark("stress_ng")

# Remote execution (dynamic inventory, uses ansible-runner)
# Recommended for full benchmarks
remote_config = BenchmarkConfig(
    remote_hosts=[RemoteHostConfig(name="node1", address="192.168.1.10", user="ubuntu")],
    remote_execution=RemoteExecutionConfig(enabled=True),
)
orchestrator = BenchmarkOrchestrator(remote_config)
summary = orchestrator.run(["stress_ng"], run_id="demo-run")
print(summary.per_host_output)

# Add a custom workload plugin (packaged in your project)
# 1. expose it via an entry point "linux_benchmark.workloads"
# 2. add its configuration under config.workloads["my_workload"]
from benchmark_config import WorkloadConfig
config.workloads["my_workload"] = WorkloadConfig(
    plugin="my_workload",  # matches the entry point name
    enabled=True,
    options={"threads": 4},
)
runner.run_benchmark("my_workload")
```

## Project Layout

```
linux-benchmark-lib/
├── benchmark_config.py      # Centralized configuration
├── orchestrator.py          # Remote orchestrator using Ansible Runner
├── local_runner.py          # Local agent for single-node runs
├── data_handler.py          # Data processing and aggregation
├── reporter.py              # Reports and plots
├── metric_collectors/       # Metric collectors
│   ├── __init__.py
│   ├── _base_collector.py   # Abstract base class
│   ├── psutil_collector.py  # PSUtil metrics
│   ├── cli_collector.py     # CLI-based metrics
│   ├── perf_collector.py    # perf events
│   └── ebpf_collector.py    # eBPF metrics
├── workload_generators/     # Workload generators
│   ├── __init__.py
│   ├── _base_generator.py   # Abstract base class
│   ├── stress_ng_generator.py
│   ├── iperf3_generator.py
│   ├── dd_generator.py
│   └── fio_generator.py
├── ansible/                 # Playbooks and roles for remote execution
│   ├── ansible.cfg
│   ├── playbooks/
│   │   ├── setup.yml
│   │   ├── run_benchmark.yml
│   │   └── collect.yml
│   └── roles/
│       ├── workload_runner/
│       └── metric_collector/
├── tests/                   # Unit and integration tests
├── docs/                    # Documentation
└── pyproject.toml           # Project configuration
```

## Configuration

All knobs are defined in `BenchmarkConfig`:

```python
from benchmark_config import BenchmarkConfig, StressNGConfig

config = BenchmarkConfig(
    # Test execution parameters
    repetitions=5,
    test_duration_seconds=120,
    metrics_interval_seconds=0.5,
    
    # stress-ng configuration
    stress_ng=StressNGConfig(
        cpu_workers=4,
        vm_workers=2,
        vm_bytes="2G"
    )
)

# Save configuration
config.save(Path("my_config.json"))

# Load configuration
config = BenchmarkConfig.load(Path("my_config.json"))
```

## Output

Results are written to three directories:

- `benchmark_results/`: raw metric data
- `reports/`: text reports and plots
- `data_exports/`: aggregated CSV/JSON
- In remote mode results are split by `run_id/host` (e.g., `benchmark_results/run-YYYYmmdd-HHMMSS/node1/...`).

## Remote Execution with Ansible Runner

- Configure targets via `RemoteHostConfig` and enable `remote_execution`.
- The controller uses `ansible-runner` with playbooks in `ansible/playbooks`:
  - `setup.yml`: base packages
  - `run_benchmark.yml`: runs `workload_runner` and `metric_collector`
  - `collect.yml`: archives and fetches per-host artifacts
- You can target `localhost` for quick checks (ensure `user` matches).
- Install dependency: `uv pip install ansible-runner`.

Final DataFrame shape:
- **Index**: Metric names (e.g., `cpu_usage_percent_avg`)
- **Columns**: Test repetitions (e.g., `Repetition_1`, `Repetition_2`)
- **Values**: Aggregated values per metric per repetition

## Testing

Run tests with pytest:

```bash
pytest tests/
```

## Contributing

1. Fork the project
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Licenza

Distribuito sotto licenza MIT. Vedi `LICENSE` per maggiori informazioni.
