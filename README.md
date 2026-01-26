<p align="center">
  <img src="docs/img/lb_mark.png" width="120" alt="Linux Benchmark Library logo" />
</p>

<h1 align="center">Linux Benchmark Library</h1>

<p align="center">
  Benchmark orchestration for Linux nodes. Repeatable workloads, rich metrics, and clean outputs.
</p>

<p align="center">
  <a href="https://miciav.github.io/linux-benchmark-lib/">Docs</a> |
  <a href="https://miciav.github.io/linux-benchmark-lib/cli/">CLI</a> |
  <a href="https://miciav.github.io/linux-benchmark-lib/api/">API Reference</a> |
  <a href="https://github.com/miciav/linux-benchmark-lib/releases">Releases</a>
</p>

<p align="center">
  <a href="https://github.com/miciav/linux-benchmark-lib/actions/workflows/pages.yml">
    <img src="https://github.com/miciav/linux-benchmark-lib/actions/workflows/pages.yml/badge.svg" alt="Docs build" />
  </a>
  <a href="https://github.com/miciav/linux-benchmark-lib/actions/workflows/diagrams.yml">
    <img src="https://github.com/miciav/linux-benchmark-lib/actions/workflows/diagrams.yml/badge.svg" alt="Diagrams build" />
  </a>
  <a href="https://github.com/miciav/linux-benchmark-lib/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/miciav/linux-benchmark-lib" alt="License" />
  </a>
  <img src="https://img.shields.io/badge/python-3.13%2B-blue" alt="Python versions" />
</p>

## Highlights

- Layered architecture: runner, controller, app, UI, analytics.
- Workload plugins via entry points and user plugin directory.
- Remote orchestration with Ansible and run journaling.
- Organized outputs: results, reports, and exports per run and host.

## Quickstart (CLI)

```bash
lb config init -i
lb plugin enable stress_ng
lb run --remote --run-id demo-run
```

Dev-only provisioning (requires `.lb_dev_cli` or `LB_ENABLE_TEST_CLI=1`):

```bash
LB_ENABLE_TEST_CLI=1 lb run --docker --run-id demo-docker
```

## Quickstart (Python)

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

## Documentation and artifacts

- Docs site: https://miciav.github.io/linux-benchmark-lib/
- API reference: https://miciav.github.io/linux-benchmark-lib/api/
- Workloads & plugins: https://miciav.github.io/linux-benchmark-lib/plugins/
- Diagrams: https://miciav.github.io/linux-benchmark-lib/diagrams/
- Diagram assets are generated on release builds and attached to the release and workflow artifacts.

## Installation

```bash
uv venv
uv pip install -e .  # runner only
```

Extras:

```bash
uv pip install -e ".[ui]"          # CLI/TUI
uv pip install -e ".[controller]"  # Ansible + analytics
uv pip install -e ".[ui,controller]"  # full CLI
uv pip install -e ".[dev]"         # test + lint tools
uv pip install -e ".[docs]"        # mkdocs
```

Switch dependency sets:

```bash
bash scripts/switch_mode.sh base
bash scripts/switch_mode.sh controller
bash scripts/switch_mode.sh headless
bash scripts/switch_mode.sh dev
```

## Project layout

```
linux-benchmark-lib/
|-- lb_runner/        # Runner (collectors, local execution helpers)
|-- lb_controller/    # Orchestration and journaling
|-- lb_app/           # Stable API for CLI/UI integrations
|-- lb_ui/            # CLI/TUI implementation
|-- lb_analytics/     # Reporting and analytics
|-- lb_plugins/       # Workload plugins and registry
|-- lb_provisioner/   # Docker/Multipass helpers
|-- lb_common/        # Shared API helpers
|-- tests/            # Unit and integration tests
|-- scripts/          # Helper scripts
`-- pyproject.toml
```

## Logging policy

- Configure logging via `lb_common.api.configure_logging()` in your entrypoint.
- `lb_ui` configures logging automatically; `lb_runner` and `lb_controller` do not.
- Keep stdout clean for `LB_EVENT` streaming when integrating custom UIs.

## Contributing

See `docs/contributing.md` for development and testing guidance.
