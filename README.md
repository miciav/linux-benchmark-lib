# Linux Benchmark Library

A robust, configurable Python library for benchmarking Linux compute nodes.

## Overview

Run repeatable workloads and collect detailed system metrics under synthetic load. The library helps you understand performance variability across repetitions and workloads.
It supports two operation modes:
1. **Agent/Runner**: Lightweight installation for target nodes (local execution).
2. **Controller**: Full orchestration layer for managing remote benchmarks (includes Ansible, plotting tools).

## Key Features

- **Multi-level metrics**: PSUtil, Linux CLI tools, perf events, optional eBPF
- **Plugin workloads**: stress-ng, dd, fio, and HPL shipped as plugins, extensible via entry points
- **Data aggregation**: Pandas DataFrames with metrics as index, repetitions as columns
- **Reporting**: Text reports and plots (Controller only)
- **Centralized config**: Typed dataclasses for all knobs
- **Remote execution**: Python controller + Ansible Runner targeting remote hosts or `localhost`

## Requirements

- Python 3.13+
- Linux for full functionality
- Root privileges for some features (perf, eBPF)

### Required External Software (Target Nodes)

- **sysstat**: sar, vmstat, iostat, mpstat, pidstat
- **stress-ng**: load generator
- **fio**: advanced I/O testing
- **HPL**: Linpack benchmark (optional)
- **perf**: Linux profiling
- **bcc/eBPF tools**: optional kernel-level metrics

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd linux-benchmark-lib
```

### Mode 1: Agent (Lightweight)
Installs only the core dependencies for running benchmarks on a target node.

```bash
uv sync
# Or install as a tool
uv tool install .
```

### Mode 2: Controller (Full)
Installs the core plus orchestration tools (Ansible) and reporting libraries (Matplotlib, Seaborn).

```bash
uv sync --extra controller
# Or install as a tool
uv tool install ".[controller]"
```

### Development
Installs all dependencies including test and linting tools.

```bash
uv sync --all-extras --dev
```

Switch between modes quickly with the helper script:

```bash
bash tools/switch_mode.sh base        # core only
bash tools/switch_mode.sh controller  # adds controller extra
bash tools/switch_mode.sh dev         # dev + all extras
```

## CLI (lb)

See `CLI.md` for the full command reference. Highlights:
- Config and defaults: `lb config init`, `lb config set-default`, `lb config edit`, `lb config workloads`, `lb plugin list --select/--enable/--disable NAME` (shows enabled state with checkmarks).
- Discovery and run: `lb plugin list`, `lb hosts`, `lb run [tests...]` (follows config for local/remote unless overridden).
- Interactive toggle: `lb plugin select` to enable/disable plugins with arrows + space; `lb config select-workloads` to toggle configured workloads the same way.
- Install plugins from a path or git repo: `lb plugin install /path/to/sysbench_plugin.tar.gz` or `lb plugin install https://github.com/miciav/unixbench-lb-plugin.git`.
- Example (UnixBench from git): 
  ```bash
  lb plugin install https://github.com/miciav/unixbench-lb-plugin.git
  lb plugin list --enable unixbench
  ```
  Then set options in `benchmark_config.json` if needed:
  ```json
  "workloads": {"unixbench": {"plugin": "unixbench", "enabled": true, "options": {"concurrency": 4}}}
  ```
- Health checks: `lb doctor controller`, `lb doctor local-tools`, `lb doctor multipass`, `lb doctor all`.
- Integration helper: `lb test multipass --vm-count {1,2} [--multi-workloads]` (artifacts to `tests/results` by default).
- Test helpers (`lb test ...`) are available in dev mode (create `.lb_dev_cli` or export `LB_ENABLE_TEST_CLI=1`).

### UI layer
- Progress bars and tables are text-friendly; headless output works in CI and when piping.
- Force headless output with `LB_HEADLESS_UI=1` when running under CI or when piping output.
- The UI adapter powers both interactive prompts and headless rendering used by tests.

### Plugin manifests and generated assets

- Each workload is self-contained in `lb_runner/plugins/<name>/`.
- Dependencies are defined in the plugin's Python class (`get_required_apt_packages`, etc.).
- A dedicated Dockerfile can be provided in the plugin directory for containerized execution.

  This updates the generated apt/pip install block in `Dockerfile` and rewrites `lb_controller/ansible/roles/workload_runner/tasks/plugins.generated.yml`.
- Commit both the manifest and generated files so remote setup and the container stay in sync with available plugins.
- See `docs/PLUGIN_DEVELOPMENT.md` for a full plugin authoring guide (WorkloadPlugin interface, manifests, packaging, git installs).
- HPL plugin: vedi `lb_runner/plugins/hpl/README.md` per note su packaging `.deb`, build VM/Docker e test `xhpl`.

## Quick Start

```python
from lb_runner.benchmark_config import BenchmarkConfig, RemoteHostConfig, RemoteExecutionConfig
from lb_controller.controller import BenchmarkController
from lb_runner.local_runner import LocalRunner
from lb_runner.plugin_system.builtin import builtin_plugins
from lb_runner.plugin_system.registry import PluginRegistry

# Create a configuration
config = BenchmarkConfig(
    repetitions=3,
    test_duration_seconds=3600,
    metrics_interval_seconds=1.0
)

# Local execution (Agent Mode)
registry = PluginRegistry(builtin_plugins())
runner = LocalRunner(config, registry=registry)
runner.run_benchmark("stress_ng")

# Remote execution (Controller Mode)
# Requires 'controller' extra installed
remote_config = BenchmarkConfig(
    remote_hosts=[RemoteHostConfig(name="node1", address="192.168.1.10", user="ubuntu")],
    remote_execution=RemoteExecutionConfig(enabled=True),
)
# Use distinct, non-empty `name` values per host; they become per-host output dirs.
controller = BenchmarkController(remote_config)
summary = controller.run(["stress_ng"], run_id="demo-run")
print(summary.per_host_output)
```

## Project Layout

```
linux-benchmark-lib/
├── lb_runner/           # Runner (plugins, collectors, local runner, events)
├── lb_controller/       # Orchestration (services, ansible, journal, data_handler)
├── lb_ui/               # CLI/UI (Typer app, adapters, reporter)
├── tests/               # Unit and integration tests
├── tools/               # Helper scripts (mode switching, etc.)
└── pyproject.toml       # Project configuration (Core + Extras)
```

## Configuration

All knobs are defined in `BenchmarkConfig`:

```python
from pathlib import Path
from lb_runner.benchmark_config import BenchmarkConfig
from lb_runner.plugins.stress_ng.plugin import StressNGConfig

config = BenchmarkConfig(
    repetitions=5,
    test_duration_seconds=120,
    metrics_interval_seconds=0.5,
    plugin_settings={
        "stress_ng": StressNGConfig(
            cpu_workers=4,
            vm_workers=2,
            vm_bytes="2G",
        )
    },
)

config.save(Path("my_config.json"))
config = BenchmarkConfig.load(Path("my_config.json"))
```

## Output

Results are written to three directories:

- `benchmark_results/`: raw metric data
- `reports/`: text reports and plots
- `data_exports/`: aggregated CSV/JSON
- In remote mode results are split by `run_id/host` (e.g., `benchmark_results/run-YYYYmmdd-HHMMSS/node1/...`).

## Contributing

1. Fork the project
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Licenza

Distribuito sotto licenza MIT. Vedi `LICENSE` per maggiori informazioni.
