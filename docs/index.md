# Home

A robust, configurable Python library for benchmarking Linux compute nodes.

## Overview

Run repeatable workloads and collect detailed system metrics under synthetic load. The library helps you understand performance variability across repetitions and workloads.
It supports two operation modes:
1. **Agent/Runner**: Lightweight installation for target nodes (local execution).
2. **Controller**: Full orchestration layer for managing remote benchmarks (includes Ansible, plotting tools).
3. **UI/CLI**: User interaction lives in `lb_ui` and talks only to the controller; the runner does not import or know about UI concerns.

## Key Features

- **Multi-level metrics**: PSUtil, Linux CLI tools, perf events, optional eBPF
- **Plugin workloads**: stress-ng, dd, fio, and HPL shipped as plugins, extensible via entry points
- **Data aggregation**: Pandas DataFrames with metrics as index, repetitions as columns
- **Reporting**: Text reports and plots (Controller only)
- **Centralized config**: Typed dataclasses for all knobs
- **Remote execution**: Python controller + Ansible Runner targeting remote hosts or `localhost`

## Requirements

- Python 3.13+
- Linux for full functionality
- Root privileges for some features (perf, eBPF)

### Required External Software (Target Nodes)

- **sysstat**: sar, vmstat, iostat, mpstat, pidstat
- **stress-ng**: load generator
- **fio**: advanced I/O testing
- **HPL**: Linpack benchmark (optional)
- **perf**: Linux profiling
- **bcc/eBPF tools**: optional kernel-level metrics


```

## CLI (lb)

See `CLI.md` for the full command reference. Highlights:
- Config and defaults: `lb config init`, `lb config set-default`, `lb config edit`, `lb config workloads`, `lb plugin list --select/--enable/--disable NAME` (shows enabled state with checkmarks).
- Discovery and run: `lb plugin list`, `lb hosts`, `lb run [tests...]` (follows config for local/remote unless overridden).
- Interactive toggle: `lb plugin select` to enable/disable plugins with arrows + space; `lb config select-workloads` to toggle configured workloads the same way.
- Install plugins from a path or git repo: `lb plugin install /path/to/sysbench_plugin.tar.gz` or `lb plugin install https://github.com/miciav/unixbench-lb-plugin.git`.
- Third-party plugins are installed under `lb_runner/plugins/_user` when that directory is writable (e.g., in a repo checkout or remote runner tree), so moving the runner also moves installed plugins. If not writable, the installer falls back to `~/.config/lb/plugins`. You can override the location with `LB_USER_PLUGIN_DIR`.
- Example (UnixBench from git): 
  ```bash
  lb plugin install https://github.com/miciav/unixbench-lb-plugin.git
  lb plugin list --enable unixbench
  ```
  Then set options in `benchmark_config.json` if needed:
  ```json
  "workloads": {"unixbench": {"plugin": "unixbench", "enabled": true, "options": {"concurrency": 4}}}
  ```
- Health checks: `lb doctor controller`, `lb doctor local-tools`, `lb doctor multipass`, `lb doctor all`.
- Integration helper: `lb test multipass --vm-count {1,2} [--multi-workloads]` (artifacts to `tests/results` by default).
- Test helpers (`lb test ...`) are available in dev mode (create `.lb_dev_cli` or export `LB_ENABLE_TEST_CLI=1`).

### UI layer
- The CLI/UI entrypoint is `python -m lb_ui.cli` (or the installed `lb` shim). Runner/controller modules no longer import UI.
- Progress bars and tables are text-friendly; headless output works in CI and when piping.
- Force headless output with `LB_HEADLESS_UI=1` when running under CI or when piping output.
- UI adapters live in `lb_ui/ui/*` and depend on controller-owned interfaces (`lb_controller.ui_interfaces`); the runner only emits events/logs.

### Plugin manifests and generated assets

- Each workload is self-contained in `lb_runner/plugins/<name>/`.
- Dependencies are defined in the plugin's Python class (`get_required_apt_packages`, etc.).
- Commit manifests so remote setup stays in sync with available plugins.
- See `docs/PLUGIN_DEVELOPMENT.md` for a full plugin authoring guide (WorkloadPlugin interface, manifests, packaging, git installs).
- HPL plugin: see `lb_runner/plugins/hpl/README.md` for notes on `.deb` packaging, build VM/Docker and `xhpl` testing.



## Project Layout

```
linux-benchmark-lib/
├── lb_runner/           # Runner (plugins, collectors, local runner, events)
├── lb_controller/       # Orchestration (services, ansible, journal, data_handler)
├── lb_ui/               # CLI/UI (Typer app, adapters, reporter)
├── tests/               # Unit and integration tests
├── tools/               # Helper scripts (mode switching, etc.)
└── pyproject.toml       # Project configuration (Core + Extras)
```



## Output

Results are written to three directories:

- `benchmark_results/`: raw metric data
- `reports/`: text reports and plots (via analytics)
- `data_exports/`: aggregated CSV/JSON (generated on demand via `lb analyze`)
- In remote mode results are split by `run_id/host` (e.g., `benchmark_results/run-YYYYmmdd-HHMMSS/node1/...`).

## Diagrams (UML)

The repository ships an action that generates UML class/package diagrams on each release.  
To regenerate them locally (requires Graphviz installed):

```bash
pip install "pylint==3.3.1"
mkdir -p docs/diagrams
pyreverse -o png -p linux-benchmark lb_runner lb_controller lb_ui -S
mv classes*.png docs/diagrams/classes.png
mv packages*.png docs/diagrams/packages.png
pyreverse -o puml -p linux-benchmark lb_runner lb_controller lb_ui -S
mv classes*.puml docs/diagrams/classes.puml
mv packages*.puml docs/diagrams/packages.puml
```



## License

Distributed under the MIT License. See `LICENSE` for more information.
