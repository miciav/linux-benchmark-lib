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
- Type check: `uv run basedpyright`
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

- **Ruff is pinned exactly** (`ruff==0.16.6` in dev dependencies), matching the
  `ruff-pre-commit` revision. A newer ruff in one place than the other makes the
  pre-commit hook and a local `ruff check` disagree. Bump both together.
- **Wildcards do not work in the banned-import list.** Ruff matches module paths
  component-wise; flake8's `lb_controller.services.*` syntax must be written as
  `lb_controller.services`. A key containing `*` matches nothing and silently
  disables the import-boundary check. There is a regression test for the
  boundary itself in `tests/unit/lint/test_import_boundaries.py`.

Type checking runs through basedpyright, the same checker the sibling projects
use. It replaced mypy, which needed three wrapper scripts to be useful:
`mypy` follows imports transitively, so a bare invocation traversed the vendored
code under `lb_controller/ansible` and reported misleading results, and the
scope had to be expressed as `--follow-imports=silent` plus a core/plugins split.
basedpyright only checks what `[tool.basedpyright]` `include` names, so the same
scope is now configuration, and the `scripts/mypy_*.sh` wrappers are gone.

The `include` list covers every `lb_*` package, `lb_gui` included. That makes the
gate a strict superset of what mypy gated: mypy's core and plugins scripts
skipped `lb_gui` entirely and only the advisory `mypy_all` sweep reached it.
Adding it to the gate surfaced two findings, both fixed rather than silenced —
a `Literal`-typed worker field that widened to `str` on assignment, and a member
access on an optional orchestrator that the `None` narrowing did not cover
inside a nested function.

The mypy settings were not dropped, they were mapped: its strict flags
(`disallow_untyped_defs`, `warn_return_any`, `disallow_untyped_decorators`,
`warn_unreachable`, `strict_equality`) are what basedpyright's `standard` mode
enforces by default — most of what it reported on this codebase is
`reportReturnType`, which is `warn_return_any`. The `pydantic.mypy` plugin has no
basedpyright equivalent because basedpyright understands pydantic natively, and
the four `[[tool.mypy.overrides]]` blocks that silenced missing-stub reports are
unnecessary because basedpyright resolves those packages against the venv.

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
