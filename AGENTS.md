# Repository Guidelines

## Project Structure & Module Organization
- Core configuration now lives under `lb_core/` (`benchmark_config.py`).
- Runner code is under `lb_runner/`; controller under `lb_controller/`; UI under `lb_ui/`.
- Collectors sit in `lb_runner/metric_collectors/` (PSUtil, CLI, perf, eBPF) and workload plugins in `lb_runner/plugins/` (stress-ng, dd, fio, hpl), each with base abstractions plus concrete implementations.
- Tests are under `tests/`; sample usage is in `example.py`. Output artifacts are written to `benchmark_results/`, `reports/`, and `data_exports/` (these may be absent until generated).

## Build, Test, and Development Commands
- Create env and install: `uv venv && uv pip install -e .`; include dev tools with `uv pip install -e ".[dev]"`.
- Run all tests locally: `uv run pytest tests/` (pytest is configured with strict markers and minimal output). To mirror the container flow, use `./run_tests.sh`, which builds `Dockerfile` and executes tests inside the image.
- Quick smoke run: `uv run python example.py` to execute the sample controller flow after dependencies are installed.

## Coding Style & Naming Conventions
- Python 3.13, formatted with Black (line length 88) and linted with Flake8; type checking is strict via MyPy (no untyped defs, no implicit Optional). Pydocstyle runs with D100/D104/D203/D213 ignored; keep concise docstrings for public APIs.
- Use `snake_case` for functions/variables/modules, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Prefer well-named dataclasses for configs and keep CLI/tool shelling confined to collectors/generators.

## Testing Guidelines
- Framework: pytest; tests live in `tests/` with files `test_*.py`, classes `Test*`, functions `test_*`. Favor unit tests for collectors/generators with fake command outputs and small integration tests that exercise the controller.
- Add coverage for new metrics, config validation, and error handling paths; when a test needs system tools, mark or skip so it is safe on CI/docker.

## Commit & Pull Request Guidelines
- Keep commits focused and present-tense (e.g., `Add Docker support`, `Fix pyproject discovery` as seen in history). Include issue IDs when applicable.
- For PRs, provide a short summary, how to reproduce/validate, and note any new dependencies or required privileges (perf/eBPF, stress-ng). Include logs or screenshots for report changes and mention impacts on output directories or config formats.

## Security & Environment Notes
- Some collectors require root or Linux-only tooling; avoid running perf/eBPF-heavy commands on shared hosts without approval. Prefer the Docker flow for consistent system dependencies and to isolate high-load generators.
