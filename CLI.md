CLI Reference
=============

Setup
-----
- Install in a venv: `uv venv && uv pip install -e .`
- Make `lb` globally available (optional): `uv tool install -e .`

Config resolution
-----------------
Order used by commands that need a config:
1. `-c/--config` flag
2. Saved default at `~/.config/lb/config_path` (set via `lb config set-default` or `lb config init`)
3. `./benchmark_config.json` if present
4. Built-in defaults

Top-level commands
------------------
- `lb plugins [--enable NAME | --disable NAME] [-c FILE] [--set-default]`  
  Show plugins with enabled state; optionally enable/disable a workload in the config.
- `lb hosts [-c FILE]`  
  Show remote hosts from the resolved config.
- `lb run [TEST ...] [-c FILE] [--run-id ID] [--remote/--no-remote]`  
  Run workloads locally or remotely (auto-follows config unless overridden).

Config management (`lb config ...`)
-----------------------------------
- `lb config init [-i] [--path FILE] [--set-default/--no-set-default]`  
  Create a config (prompt for a remote host with `-i`).
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
- `lb doctor local-tools` — stress-ng, iperf3, fio, sysstat tools, perf (needed only for local runs).
- `lb doctor multipass` — check presence of multipass (optional).
- `lb doctor all` — run all checks.

Integration helper (`lb test ...`)
----------------------------------
- `lb test multipass [-o DIR] [-- EXTRA_PYTEST_ARGS...]`  
  Runs the Multipass integration test; artifacts go to `tests/results` by default (override with `-o` or `LB_TEST_RESULTS_DIR`). Requires multipass + ansible/ansible-runner installed locally.
