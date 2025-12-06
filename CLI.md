CLI Reference
=============

Setup
-----
- Install in a venv: `uv venv && uv pip install -e .`
- Make `lb` globally available (optional): `uv tool install -e .`
- Enable shell completion: `lb --install-completion` (bash/zsh/fish) and restart your shell.

Config resolution
-----------------
Order used by commands that need a config:
1. `-c/--config` flag
2. Saved default at `~/.config/lb/config_path` (set via `lb config set-default` or `lb config init`)
3. `./benchmark_config.json` if present
4. Built-in defaults

Top-level commands
------------------
- `lb plugin list|ls [--select] [--enable NAME | --disable NAME] [-c FILE] [--set-default]`  
  Show plugins with enabled state; optionally enable/disable a workload in the config or open an interactive selector (arrows + space). (`lb plugins` remains as a compatibility alias.)
- `lb plugin select [-c FILE] [--set-default]`  
  Directly open the interactive selector to toggle plugins with arrows + space.
- `lb plugin install PATH|URL [--manifest FILE] [--force] [--regen-assets/--no-regen-assets]`  
  Install a plugin from a .py file, directory, archive (.zip/.tar.gz), or git repository URL.
- `lb plugin uninstall NAME [--purge-config/--keep-config] [--regen-assets/--no-regen-assets]`  
  Remove a user plugin and optionally delete its config entries.
- `lb hosts [-c FILE]`  
  Show remote hosts from the resolved config.
- `lb run [TEST ...] [-c FILE] [--run-id ID] [--remote/--no-remote] [--repetitions N]`
  Run workloads locally or remotely (auto-follows config unless overridden). Use `--repetitions` to temporarily change how many times each workload runs.
- `lb run ... --docker [--docker-image TAG] [--docker-engine docker|podman] [--docker-no-build] [--docker-no-cache]`  
  Build/use the container image and run the CLI inside it. Mounts the repo read-only and writes artifacts to the container’s `benchmark_results`.

Config management (`lb config ...`)
-----------------------------------
- `lb config init [-i] [--path FILE] [--set-default/--no-set-default]`
  Create a config (prompt for a remote host with `-i`).
- `lb config set-repetitions N [-c FILE] [--set-default/--no-set-default]`
  Persist the desired number of repetitions to a config file (defaults to `~/.config/lb/config.json`).
- `lb config set-default FILE` / `lb config unset-default` / `lb config show-default`
- `lb config edit [-p FILE]`  
  Open the config in `$EDITOR`.
- `lb config workloads [-c FILE]`  
  List workloads and enabled status.
- `lb config enable-workload NAME [-c FILE] [--set-default]`  
  (creates if missing)
- `lb config disable-workload NAME [-c FILE] [--set-default]`

Doctor checks (`lb doctor ...`)
-------------------------------
- `lb doctor controller` — Python deps + ansible/ansible-runner + config resolution.
- `lb doctor local-tools` — stress-ng, fio, sysstat tools, perf (needed only for local runs).
- `lb doctor multipass` — check presence of multipass (optional).
- `lb doctor all` — run all checks.

Integration helper (`lb test ...`, dev installs only)
-----------------------------------------------------
- Available when `.lb_dev_cli` exists in the project root or `LB_ENABLE_TEST_CLI=1` is set.
- `lb test multipass [-o DIR] [--vm-count {1,2}] [--multi-workloads] [-- EXTRA_PYTEST_ARGS...]`  
  Runs the Multipass integration test. Artifacts go to `tests/results` by default (override with `-o` or `LB_TEST_RESULTS_DIR`). `--vm-count` (or `LB_MULTIPASS_VM_COUNT`) launches 1–2 VMs. Use `--multi-workloads` to run the stress_ng + dd + fio variant. Requires multipass + ansible/ansible-runner locally.
