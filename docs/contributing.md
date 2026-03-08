## Contributing

### Development setup

```bash
uv venv
uv pip install -e ".[dev]"
```

### Tests

- Run all tests: `uv run pytest tests/`
- Containerized tests (Docker): `./run_tests.sh`
- Quick smoke run: `uv run python example.py`

### Documentation

- Install docs dependencies: `uv pip install -e ".[docs,controller]"`
- Run the site locally: `uv run mkdocs serve`

### Style and quality

- Format: `uv run black .`
- Lint: `uv run flake8`
- Type check (`core` gate): `./scripts/mypy_core.sh`
- Type check (`plugins` batch): `./scripts/mypy_plugins.sh`
- Type check (`all` advisory): `./scripts/mypy_all.sh`

`mypy` follows imports by default, so the old one-liner against `lb_runner lb_controller lb_app lb_ui`
was misleading: it still traversed transitive packages and vendored code under `lb_controller/ansible`.
The scripts above make the scope explicit:

- `mypy_core.sh`: checks `lb_runner`, `lb_controller`, `lb_app`, `lb_ui` with `--follow-imports=silent`
- `--follow-imports=silent` is intentional: `skip` suppresses the `pydantic.mypy` plugin and causes false `untyped-decorator` errors on `@model_validator`
- `mypy_plugins.sh`: checks plugin/provisioning code
- `mypy_all.sh`: checks the full first-party repo surface as an advisory sweep

### PR checklist

- Keep commits focused and present tense.
- Note any required privileges (perf/eBPF, stress-ng, Docker, Multipass).
- Include validation steps and relevant logs/screenshots.
