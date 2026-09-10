## Contributing

### Development setup

```bash
uv sync --all-extras
uv run pre-commit install
```

### Tests

- Run all tests: `uv run pytest tests/`
- Unit tests only: `uv run pytest tests/unit`
- With coverage: `./scripts/run_tests_with_cov.sh`
- Quick smoke run: `uv run python example.py`

### Documentation

- Install docs dependencies: `uv pip install -e ".[docs,controller]"`
- Run the site locally: `uv run mkdocs serve`

### Style and quality

Everything below is wired into `.pre-commit-config.yaml`, and CI runs the same
hooks. The shortest correct path is:

```bash
uv run pre-commit run --all-files
```

The individual commands, if you want them:

- Lint: `uv run ruff check .` (add `--fix` to apply safe autofixes)
- Format: `uv run ruff format .`
- Type check (`core` gate): `./scripts/mypy_core.sh`
- Type check (`plugins` batch): `./scripts/mypy_plugins.sh`
- Type check (`all` advisory): `./scripts/mypy_all.sh`
- Architecture contracts: `uv run lint-imports` and
  `uv run python scripts/check_api_imports.py`
- Security: `uv run bandit -c pyproject.toml -r <pkg>`,
  `uv run semgrep --config .semgrep.yml`, `uv run pip-audit`
- Dependencies: `uv run deptry .`
- YAML / Ansible: `uv run yamllint -c .yamllint.yaml .` (or the pre-commit hook)

Ruff replaces what used to be four separate tools — black, flake8,
flake8-tidy-imports and pydocstyle — so their configs are gone (`.flake8` was
deleted and the banned-module list moved to
`[tool.ruff.lint.flake8-tidy-imports.banned-api]`).

Two things worth knowing:

- **Ruff is pinned exactly** (`ruff==0.14.10` in dev dependencies), matching the
  `ruff-pre-commit` revision. A newer ruff in one place than the other makes the
  pre-commit hook and a local `ruff check` disagree. Bump both together.
- **Wildcards do not work in the banned-import list.** Ruff matches module paths
  component-wise; flake8's `lb_controller.services.*` syntax must be written as
  `lb_controller.services`. A key containing `*` matches nothing and silently
  disables the import-boundary check. There is a regression test for the
  boundary itself in `tests/unit/lint/test_import_boundaries.py`.

`mypy` follows imports by default, so the old one-liner against `lb_runner lb_controller lb_app lb_ui`
was misleading: it still traversed transitive packages and vendored code under `lb_controller/ansible`.
The scripts above make the scope explicit:

- `mypy_core.sh`: checks `lb_runner`, `lb_controller`, `lb_app`, `lb_ui` with `--follow-imports=silent`
- `--follow-imports=silent` is intentional: `skip` suppresses the `pydantic.mypy` plugin and causes false `untyped-decorator` errors on `@model_validator`
- `mypy_plugins.sh`: checks plugin/provisioning code
- `mypy_all.sh`: checks the full first-party repo surface as an advisory sweep

### Known gaps

- Ruff has no implementation of flake8-cognitive-complexity, so the old `CCR001`
  check has no direct replacement. Complexity is covered by the radon/xenon sweep
  in `scripts/arch_audit.sh`; SonarQube/SonarCloud is the option if cognitive
  complexity specifically is wanted as a gate.
- The docstring rules for *missing* docstrings (D100–D107) are disabled. Ruff
  flags an order of magnitude more of these than pydocstyle did, so documenting
  the public API is tracked as its own task rather than silently enabled.
- `tests/integration/lb_plugins/test_dfaas_docker_integration.py::test_dfaas_end_to_end_with_docker`
  fails, and CI excludes it via `-m "not inter_docker"`. The test's own Ansible
  stub only fetches the k6 summary when `SUMMARY_FETCH_DEST` is non-empty, and
  the plugin never passes `summary_fetch_dest`, so nothing is collected and the
  exported `summaries/`, `metrics/` and `k6_scripts/` directories come out
  empty. Docker and the k6 image both work on this machine, so it is not an
  environment problem. Tests carrying the `inter_docker` marker need a Docker
  daemon and belong in their own CI job.
- The Ansible surface has a pre-existing backlog of 201 ansible-lint findings;
  see `.ansible-lint` for the per-rule counts. The rules that currently fire are
  advisory, so a new rule violation still fails the build.

### PR checklist

- Keep commits focused and present tense.
- Note any required privileges (perf/eBPF, stress-ng, Docker, Multipass).
- Include validation steps and relevant logs/screenshots.
