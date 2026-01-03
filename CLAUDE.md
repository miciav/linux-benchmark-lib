# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

```bash
# Setup
uv venv && uv pip install -e ".[dev]"

# Run tests
uv run pytest tests/                          # all tests
uv run pytest tests/unit/                     # unit tests only
uv run pytest -m "unit"                       # by marker
uv run pytest -m "not e2e and not multipass"  # exclude slow tests
uv run pytest tests/unit/lb_runner/test_foo.py::test_bar  # single test

# Quick smoke test
uv run python example.py

# Linting & formatting
uv run black .
uv run flake8
uv run mypy lb_runner lb_controller lb_app lb_ui

# Docs
uv pip install -e ".[docs,controller]"
uv run mkdocs serve
```

## Architecture

The library follows a layered architecture with strict import boundaries:

```
lb_ui/           → lb_app/          → lb_controller/  → lb_runner/
(CLI/TUI)          (Stable facade)     (Orchestration)    (Execution)
                                             ↓
                                       lb_plugins/
                                       (Workloads)
```

**Module responsibilities:**
- `lb_runner/` - Core execution: metric collectors (PSUtil, CLI, perf, eBPF), local runner
- `lb_controller/` - Remote orchestration via Ansible, run journaling, state machine
- `lb_app/` - Stable API facade for CLI/UI integrations
- `lb_ui/` - CLI/TUI implementation (does not import into runner/controller)
- `lb_analytics/` - Data aggregation and reporting (Pandas, Matplotlib)
- `lb_plugins/` - Workload plugins (stress-ng, fio, dd, hpl, stream, dfaas)
- `lb_provisioner/` - Docker/Multipass provisioning helpers
- `lb_common/` - Shared utilities and logging configuration

**Key rules:**
- Always use the public `api.py` exports: `lb_runner.api`, `lb_controller.api`, `lb_app.api`
- Never import internal modules directly (enforced by flake8-tidy-imports in `.flake8`)
- Configure logging via `lb_common.api.configure_logging()` in entrypoints
- Keep stdout clean for `LB_EVENT` streaming when building custom UIs

## Plugin System

Workloads are registered via Python entry points in `pyproject.toml`:

```toml
[project.entry-points."linux_benchmark.workloads"]
stress_ng = "lb_plugins.plugins.stress_ng.plugin:PLUGIN"
```

Each plugin in `lb_plugins/plugins/<name>/` contains:
- `plugin.py` - Plugin definition and `PLUGIN` constant
- `generator.py` - Command generation logic
- `ansible/` - Optional Ansible playbooks for setup/teardown

## Test Organization

Tests live in `tests/` with markers for filtering:
- `tests/unit/` - Fast, isolated tests (subdirs: `lb_runner/`, `lb_controller/`, etc.)
- `tests/integration/` - Service-level tests, no provisioning
- `tests/e2e/` - Full end-to-end with Multipass VMs or Docker
- `tests/fixtures/` - Static test data

Markers: `unit`, `integration`, `e2e`, `docker`, `multipass`, `slow`, `slowest`

## Output Directories

Generated at runtime (gitignored):
- `benchmark_results/` - Raw metric data per run
- `reports/` - Generated text reports and plots
- `data_exports/` - Exported data files

## Style

- Python 3.12+, Black (88 chars), strict MyPy
- `snake_case` for functions/variables, `PascalCase` for classes
- Prefer dataclasses for configuration objects
