# Linux Benchmark Library (linux-benchmark-lib)

## Project Overview
`linux-benchmark-lib` is a robust, configurable Python library designed for benchmarking Linux compute nodes. It supports running repeatable workloads and collecting detailed system metrics under synthetic load.

### Key Features
*   **Operation Modes:**
    *   **Agent (Local):** Lightweight installation for target nodes.
    *   **Controller (Remote):** Full orchestration layer using Ansible for managing remote benchmarks.
    *   **UI/CLI:** TUI-based interaction (via `rich` and `typer`).
*   **Metric Collection:** PSUtil, Linux CLI tools, perf events, eBPF.
*   **Workloads:** Plugin-based system (stress-ng, dd, fio, hpl, stream). Extensible via Python entry points.
*   **Data Handling:** Aggregation using Pandas, reporting with Matplotlib/Seaborn.

## Architecture
*   `lb_runner/`: Core execution logic, workload plugins, and metric collectors.
    *   `local_runner.py`: Orchestrates the benchmark workflow on a single node.
*   `lb_controller/`: Remote orchestration, Ansible integration, and result handling.
*   `lb_ui/`: CLI and TUI layer. **Note:** Runner/Controller modules do not import UI components.
*   `lb_analytics/`: Data aggregation and reporting logic.
*   `benchmark_results/`: Stores raw metric data.
*   `reports/`: Generated text reports and plots.

## Development & Usage

### Setup
The project uses `uv` for dependency management.

```bash
# Install core dependencies
uv sync

# Install controller extras (Ansible, plotting)
uv sync --extra controller

# Install dev dependencies
uv sync --all-extras --dev
```

### Key Commands (`lb`)
The CLI entry point is `lb` (or `python -m lb_ui.cli`).

*   **Run Benchmarks:**
    *   `lb run [workload_name]` (e.g., `lb run stress_ng`)
    *   `lb run --remote` (uses configured remote hosts)
*   **Plugin Management:**
    *   `lb plugin list` (show status)
    *   `lb plugin install <url/path>`
*   **Configuration:**
    *   `lb config init` (initialize config)
    *   `lb config edit` (open in editor)
*   **Diagnostics:**
    *   `lb doctor all` (run health checks)

### Testing
Tests are managed with `pytest` and marked for different scopes.

```bash
# Run all tests
uv run pytest tests/

# Run specific types
uv run pytest -m unit
uv run pytest -m integration
uv run pytest -m tui
```

### Coding Standards
*   **Style:** `black` (line length 88), `flake8`.
*   **Typing:** Strict `mypy` (Python 3.12+).
*   **Docstrings:** `pydocstyle` (subset of rules).
*   **Conventions:** `snake_case` for functions/vars, `PascalCase` for classes. Dataclasses for configuration.

## File Structure Highlights
*   `pyproject.toml`: Dependency and build configuration.
*   `lb_runner/benchmark_config.py`: Configuration dataclasses.
*   `lb_plugins/plugins/`: Workload plugin implementations.
*   `lb_controller/ansible/`: Ansible playbooks and roles.
