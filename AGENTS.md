# Repository Guidelines

## Project Structure & Module Organization
- Core configuration lives under `lb_runner/` (`benchmark_config.py`).
- Runner code is under `lb_runner/`; controller under `lb_controller/`; app-layer API under `lb_app/`; UI under `lb_ui/`.
- Reporting and post-processing live under `lb_analytics/`; shared utilities in `lb_common/`; provisioning helpers in `lb_provisioner/`.
- Use the stable APIs from `lb_runner.api`, `lb_controller.api`, and `lb_app.api` instead of importing deep modules.
- UI layering: `lb_ui` may import only `lb_app.api` (and `lb_common.api` when needed). Avoid any direct imports from `lb_controller`, `lb_runner`, `lb_plugins`, `lb_analytics`, or `lb_provisioner`.
- Collectors sit in `lb_runner/metric_collectors/` (PSUtil, CLI, perf, eBPF) and workload plugins in `lb_plugins/plugins/` (stress-ng, dd, fio, hpl), each with base abstractions plus concrete implementations.
- Tests are under `tests/`; sample usage is in `example.py`. Output artifacts are written to `benchmark_results/`, `reports/`, and `data_exports/` (these may be absent until generated).

## Build, Test, and Development Commands
- Create env and install: `uv sync --all-extras`. Do **not** use `uv pip install -e ".[dev]"` for development: the lint/type/security toolchain (ruff, basedpyright, pre-commit, bandit, semgrep, deptry, yamllint, ansible-lint, import-linter) is declared in `[dependency-groups].dev`, which `uv sync` installs and the `dev` extra does not. Then enable the hooks with `uv run pre-commit install`.
- Run all tests locally: `uv run pytest tests/` (pytest is configured with strict markers and minimal output). For coverage, use `./scripts/run_tests_with_cov.sh`.
- Quick smoke run: `uv run python example.py` to execute the sample controller flow after dependencies are installed.

## Coding Style & Naming Conventions
- Python 3.12+ (the `requires-python` floor; CI also runs 3.13). Linting **and** formatting are done by Ruff (line length 88) with `basedpyright` in standard mode for types (configured in `[tool.basedpyright]`; no untyped defs, no implicit Optional). Ruff also holds the pydocstyle rules that used to run via the `pydocstyle` tool, with the missing-docstring family and D203/D213 ignored — keep concise docstrings for public APIs.
- Use `snake_case` for functions/variables/modules, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Prefer well-named dataclasses for configs and keep CLI/tool shelling confined to collectors/generators.
- Logging policy: configure logging via `lb_common.configure_logging()` in entrypoints. `lb_runner` does not auto-configure logging; callers should opt in to keep `LB_EVENT` output on stdout clean.
- Run `uv run pre-commit run --all-files` before pushing: it is the same hook set CI runs, so a green local run means a green pipeline.

## Testing Guidelines
- Framework: pytest; tests live in `tests/` with files `test_*.py`, classes `Test*`, functions `test_*`. Favor unit tests for collectors/generators with fake command outputs and small integration tests that exercise the controller.
- Add coverage for new metrics, config validation, and error handling paths; when a test needs system tools, mark or skip so it is safe on CI/docker.

## Commit & Pull Request Guidelines
- Keep commits focused and present-tense (e.g., `Add Docker support`, `Fix pyproject discovery` as seen in history). Include issue IDs when applicable.
- For PRs, provide a short summary, how to reproduce/validate, and note any new dependencies or required privileges (perf/eBPF, stress-ng). Include logs or screenshots for report changes and mention impacts on output directories or config formats.

## Security & Environment Notes
- Some collectors require root or Linux-only tooling; avoid running perf/eBPF-heavy commands on shared hosts without approval. Prefer the Docker flow for consistent system dependencies and to isolate high-load generators.

## Worktree Cleanup (Submodules)
- If a worktree contains submodules, remove it with `scripts/remove_worktree_with_submodules.sh /path/to/worktree` (this deinitializes submodules first, then force-removes the worktree).
