# Linux Benchmark Library - QWEN Context

## Project Overview

The Linux Benchmark Library (LBB) is a robust and configurable Python library for benchmarking Linux computational node performance. It provides a layered architecture for orchestrating repeatable workloads, collecting rich metrics, and producing clean outputs.

### Key Features
- **Layered Architecture**: Runner, controller, app, UI, and analytics components
- **Workload Plugins**: Extensible via entry points and user plugin directory
- **Remote Orchestration**: Uses Ansible with run journaling
- **Organized Outputs**: Results, reports, and exports per run and host
- **Multiple Execution Modes**: Local, remote, Docker, and Multipass execution

### Project Structure
```
linux-benchmark-lib/
├── lb_runner/        # Runner (collectors, local execution helpers)
├── lb_controller/    # Orchestration and journaling
├── lb_app/           # Stable API for CLI/UI integrations
├── lb_ui/            # CLI/TUI implementation
├── lb_analytics/     # Reporting and analytics
├── lb_plugins/       # Workload plugins and registry
├── lb_provisioner/   # Docker/Multipass helpers
├── lb_common/        # Shared API helpers
└── tests/            # Unit and integration tests
```

## Architecture Components

### lb_runner
- Core benchmark execution engine
- Local metric collection system
- Plugin execution framework
- System information gathering

### lb_controller
- Remote orchestration engine
- Ansible integration
- Run journaling and state management
- Lifecycle management and interrupt handling

### lb_plugins
- Workload plugin system with built-in plugins (stress_ng, fio, dd, hpl, stream, etc.)
- Plugin registry and discovery system
- Configuration models for each workload type

### lb_ui
- Command-line interface (CLI) and text user interface (TUI)
- Typer-based command structure
- Configuration management

### lb_common
- Shared utilities and configuration helpers
- Logging and observability components
- Environment variable parsing

## Building and Running

### Installation
```bash
# Create virtual environment
uv venv

# Install in different modes
uv pip install -e .                    # runner only
uv pip install -e ".[ui]"              # CLI/TUI
uv pip install -e ".[controller]"      # Ansible + analytics
uv pip install -e ".[ui,controller]"   # full CLI
uv pip install -e ".[dev]"             # test + lint tools
uv pip install -e ".[docs]"            # mkdocs
```

### Switching Dependency Sets
```bash
bash scripts/switch_mode.sh base        # Base runner only
bash scripts/switch_mode.sh controller  # Full CLI with UI
bash scripts/switch_mode.sh headless    # Controller without UI
bash scripts/switch_mode.sh dev         # Development mode
```

### Quick Start (CLI)
```bash
# Initialize configuration
lb config init -i

# Enable a plugin and run
lb plugin list --enable stress_ng
lb run --remote --run-id demo-run

# Development Docker run
LB_ENABLE_TEST_CLI=1 lb run --docker --run-id demo-docker
```

### Quick Start (Python API)
```python
from lb_controller.api import (
    BenchmarkConfig,
    BenchmarkController,
    RemoteExecutionConfig,
    RemoteHostConfig,
)

config = BenchmarkConfig(
    repetitions=2,
    remote_hosts=[
        RemoteHostConfig(name="node1", address="192.168.1.10", user="ubuntu")
    ],
    remote_execution=RemoteExecutionConfig(enabled=True),
)

controller = BenchmarkController(config)
summary = controller.run(["stress_ng"], run_id="demo-run")
print(summary.per_host_output)
```

## Key APIs

### Runner API
- `LocalRunner`: Core local benchmark execution
- `BenchmarkConfig`: Configuration for benchmark runs
- `MetricCollectorConfig`: Configuration for metric collection
- `WorkloadConfig`: Configuration for individual workloads

### Controller API
- `BenchmarkController`: Remote orchestration controller
- `RunJournal`: Run state and journaling
- `RunLifecycle`: Run phase management
- `StopCoordinator`: Interrupt and stop handling

### Plugin API
- `WorkloadPlugin`: Base class for workload plugins
- `BasePluginConfig`: Base configuration for plugins
- `PluginRegistry`: Plugin discovery and management
- Various plugin-specific configs (StressNGConfig, FIOConfig, etc.)

## Development Conventions

### Logging Policy
- Configure logging via `lb_common.api.configure_logging()` in entrypoints
- `lb_ui` configures logging automatically; `lb_runner` and `lb_controller` do not
- Keep stdout clean for `LB_EVENT` streaming when integrating custom UIs

### Testing
- Unit tests marked with specific markers (unit_runner, unit_controller, etc.)
- Integration tests with different levels (inter_generic, inter_docker, inter_multipass, etc.)
- Slow tests marked with `slow` and `slowest` markers

### Code Quality
- Uses mypy for type checking
- Black for code formatting
- Pytest for testing
- Various linting tools (flake8, vulture, etc.)

## Available Workload Plugins

The library includes several built-in workload plugins:
- **stress_ng**: CPU, memory, I/O stress testing
- **fio**: Flexible I/O tester
- **dd**: Basic disk I/O operations
- **hpl**: High Performance Linpack
- **stream**: Memory bandwidth test
- **sysbench**: System performance benchmark
- **geekbench**: Cross-platform benchmark
- **unixbench**: Unix system benchmark
- **yabs**: Yet Another Benchmark Suite
- **phoronix_test_suite**: Phoronix test framework

## Documentation and Resources

- Documentation site: https://miciav.github.io/linux-benchmark-lib/
- API reference: https://miciav.github.io/linux-benchmark-lib/api/
- Workloads & plugins: https://miciav.github.io/linux-benchmark-lib/plugins/
- Diagrams: https://miciav.github.io/linux-benchmark-lib/diagrams/

## CLI Commands

The main CLI provides several command groups:
- `lb config`: Configuration management
- `lb plugin`: Plugin management and listing
- `lb run`: Running benchmarks
- `lb provision`: Environment provisioning
- `lb runs`: Run history and management
- `lb doctor`: System checks and diagnostics