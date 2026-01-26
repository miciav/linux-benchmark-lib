# CLI Reference

> Note: the user-facing CLI lives in `lb_ui` (invoke via `lb` or `python -m lb_ui.cli`). Runner/controller packages do not expose separate entrypoints.

## Setup

- Install in a venv: `uv venv && uv pip install -e .`
- Make `lb` globally available (optional): `uv tool install -e .`
- Enable shell completion: `lb --install-completion` (bash/zsh/fish)

## Global flags

- `--headless` forces headless output (useful in CI or pipes).

## Config resolution

Order used by commands that need a config:

1. `-c/--config` flag
2. Saved default at `~/.config/lb/config_path` (set via `lb config set-default` or `lb config init`)
3. `./benchmark_config.json` if present
4. Built-in defaults

## Top-level commands

- `lb run [WORKLOAD ...] [-c FILE] [--run-id ID] [--remote/--no-remote] [--repetitions N] [--intensity LEVEL] [--setup/--no-setup] [--stop-file PATH] [--debug]`
  Run workloads remotely via Ansible. Local execution is not supported by the CLI.
- `lb run ... --docker [--docker-engine docker|podman] [--nodes N]`
  Dev-only: provision containers and run via Ansible (requires `.lb_dev_cli` or `LB_ENABLE_TEST_CLI=1`).
- `lb run ... --multipass [--nodes N]`
  Dev-only: provision Multipass VMs and run via Ansible (requires `.lb_dev_cli` or `LB_ENABLE_TEST_CLI=1`).
- `lb resume [RUN_ID] [-c FILE] [--remote/--no-remote] [--docker|--multipass] [--nodes N] [--intensity LEVEL] [--setup/--no-setup] [--stop-file PATH] [--debug]`
  Resume an incomplete run using a stored journal.
- `lb runs list [--root PATH] [-c FILE]` / `lb runs show RUN_ID [--root PATH] [-c FILE]`
  Inspect stored runs under `benchmark_results/`.
- `lb runs analyze [RUN_ID] [--root PATH] [--workload NAME] [--host NAME]`
  Run analytics on an existing run (currently `aggregate`).
- `lb plugin ...`
  Inspect and manage workload plugins.
- `lb config ...`
  Create and manage benchmark configuration files.
- `lb doctor ...`
  Run prerequisite checks.
- `lb test multipass ...` (dev-only)
  Helper to run integration tests.

## Plugin management (`lb plugin ...`)

- `lb plugin list`
- `lb plugin enable NAME`
- `lb plugin disable NAME`
- `lb plugin select`

## Config management (`lb config ...`)

- `lb config init [-i] [-c FILE] [--set-default/--no-set-default]`
- `lb config set-repetitions N [-c FILE] [--set-default/--no-set-default]`
- `lb config set-default FILE` / `lb config unset-default` / `lb config show-default`
- `lb config edit [-c FILE]`
- `lb config workloads [-c FILE]`
- `lb config enable-workload NAME [-c FILE] [--set-default]`
- `lb config disable-workload NAME [-c FILE] [--set-default]`
- `lb config select-workloads [-c FILE] [--set-default]`

## Doctor checks (`lb doctor ...`)

- `lb doctor controller` - Python deps + Ansible requirements
- `lb doctor local` - local workload tools (stress-ng, fio, sysstat)
- `lb doctor multipass` - Multipass availability
- `lb doctor all` - run all checks

## Test helpers (`lb test ...`, dev installs only)

- Available when `.lb_dev_cli` exists in the project root or `LB_ENABLE_TEST_CLI=1` is set.
- `lb test multipass [-o DIR] [--vm-count {1,2}] [--multi-workloads] [-- EXTRA_PYTEST_ARGS...]`

## Environment variables

- `LB_ENABLE_TEST_CLI=1` enables `lb test` and provisioning flags in the CLI.
- `LB_USER_PLUGIN_DIR` overrides the user plugin install directory.
- `LB_STOP_FILE` sets a stop sentinel path if `--stop-file` is omitted.
- `LB_TEST_RESULTS_DIR`, `LB_MULTIPASS_VM_COUNT` customize test helpers.
