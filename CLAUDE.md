# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

```bash
# Setup
# Use `uv sync`, not `uv pip install -e ".[dev]"`. The lint/type/security
# toolchain (ruff, basedpyright, pre-commit, bandit, semgrep, deptry, yamllint,
# ansible-lint, import-linter) lives in [dependency-groups].dev, which
# `uv sync` installs and `uv pip install -e ".[dev]"` does not.
uv sync --all-extras
uv run pre-commit install

# Run tests
uv run pytest tests/                          # all tests
uv run pytest tests/unit/                     # unit tests only
uv run pytest -m "unit"                       # by marker
uv run pytest -m "not e2e and not multipass"  # exclude slow tests
uv run pytest tests/unit/lb_runner/test_foo.py::test_bar  # single test

# Quick smoke test
uv run python example.py

# Linting & formatting (ruff replaces black, flake8 and pydocstyle)
uv run ruff check .                           # lint
uv run ruff check --fix .                     # lint + safe autofixes
uv run ruff format .                          # format

# Type checking - one invocation, no scripts. basedpyright checks exactly what
# [tool.basedpyright] `include` names, so it stays out of the vendored Ansible
# collections without the scoping flags mypy needed.
uv run basedpyright                           # type check

# Everything at once, the same way CI does it
uv run pre-commit run --all-files

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
- Never import internal modules directly (enforced by ruff `TID251`, configured in
  `[tool.ruff.lint.flake8-tidy-imports.banned-api]` in `pyproject.toml`)
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

- Python 3.12+ (the floor; CI also tests 3.13), ruff for linting and formatting (88 chars), basedpyright in standard mode
- `snake_case` for functions/variables, `PascalCase` for classes
- Prefer dataclasses for configuration objects
- Test data files use `snake_case` too; the `tests/` tree is excluded from ruff's
  docstring rules

## Tooling

Quality is enforced by `.pre-commit-config.yaml` locally and
`.github/workflows/ci.yml` in CI. CI runs the same pre-commit hooks, so
local and CI results cannot drift.

| Concern | Tool | Config |
| --- | --- | --- |
| Lint + format | ruff | `[tool.ruff]` in `pyproject.toml` |
| Types | basedpyright | `[tool.basedpyright]`, standard mode |
| Import layers | import-linter, `scripts/check_api_imports.py` | `[tool.importlinter]` |
| Security | bandit, semgrep, pip-audit | `[tool.bandit]`, `.semgrep.yml` |
| Dependencies | deptry | `[tool.deptry]` |
| Dead code | vulture | `scripts/run_vulture.sh` |
| YAML / Ansible | yamllint, ansible-lint | `.yamllint.yaml`, `.ansible-lint` |
| Coverage | pytest-cov | `[tool.coverage.*]` |

Note: ruff has **no** implementation of flake8-cognitive-complexity, so the
former `CCR001` check has no ruff equivalent. Complexity is covered by the
radon/xenon sweep in `scripts/arch_audit.sh`; SonarQube/SonarCloud cognitive
complexity is the option if that specific metric is wanted in CI.

## Import Boundary Rules

**lb_controller must only be imported via lb_controller.api** from other packages (lb_app, lb_ui, lb_plugins, etc.).

Direct imports like `from lb_controller.services.X import Y` or `from lb_controller.engine.X import Y` are violations when done from outside lb_controller/.

This rule is enforced by ruff rule `TID251` (configured in
`[tool.ruff.lint.flake8-tidy-imports.banned-api]`), by the layer contracts in
`[tool.importlinter]`, and by `tests/unit/lint/test_import_boundaries.py`.

**When editing that banned list:** ruff matches banned module paths
component-wise and does **not** understand flake8's `a.b.*` wildcard syntax. A
key containing a wildcard matches nothing and silently disables the rule —
keep the keys wildcard-free.
