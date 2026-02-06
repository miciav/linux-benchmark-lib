# Plugin Dependency Lifecycle

## Plugin-scoped UV extras

Workload plugins can declare Python dependency extras through
`PluginAssetConfig.required_uv_extras` and `WorkloadPlugin.get_required_uv_extras()`.
This keeps plugin-specific packages out of global `[project.dependencies]`.

For PEVA-FAAS, the optional extra is `peva_faas` and contains:
- `duckdb`
- `pyarrow`

## Runtime resolution flow

1. Plugin metadata is resolved into `config.plugin_assets`.
2. Controller `ExtravarsBuilder` gathers extras only from enabled workloads.
3. The deduplicated list is placed in `lb_uv_extras`.
4. Global setup converts the list into `--extra <name>` flags and runs:
   `uv sync --frozen --no-dev {{ lb_uv_extra_args }}`.

If no enabled workload declares extras, `lb_uv_extras` is empty and setup behavior
remains unchanged.

## Setup and teardown contract

- `setup_plugin.yml` remains the plugin setup entrypoint for plugin runtime assets
  such as `k6` and `faas-cli`.
- Global controller setup installs Python dependencies through UV extras.
- Plugin teardown is limited to explicit, opt-in cleanup tasks.

For PEVA-FAAS, teardown supports optional cleanup of memory assets via:
- `peva_faas_memory_cleanup` (default `false`)
- `peva_faas_memory_paths` (default `[]`)

Cleanup is guarded and only allowed under:
- `benchmark_results/peva_faas`
- `~/.peva_faas-k6`
