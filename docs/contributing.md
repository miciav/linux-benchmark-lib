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

### Style and quality

- Format: `uv run black .`
- Lint: `uv run flake8`
- Type check: `uv run mypy lb_runner lb_controller lb_app lb_ui`

### PR checklist

- Keep commits focused and present tense.
- Note any required privileges (perf/eBPF, stress-ng, Docker, Multipass).
- Include validation steps and relevant logs/screenshots.
