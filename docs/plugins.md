# Workloads and Plugins

Linux Benchmark Library exposes workloads as plugins. The registry loads built-in
plugins, entry point plugins, and user plugins from the configured plugin directory.

## Built-in plugins

| Plugin | Summary | Notes |
| --- | --- | --- |
| `baseline` | No-op workload for baseline overhead. | Useful to measure collector overhead. |
| `stress_ng` | CPU/memory stress via stress-ng. | CLI tools required on hosts. |
| `dd` | Disk write workload via dd. | Writes test files under output dirs. |
| `fio` | Storage workload via fio. | Supports debug flag in CLI. |
| `hpl` | Linpack HPL benchmark. | Requires packaged binaries or setup playbooks. |
| `stream` | Memory bandwidth via STREAM. | Optional local build step. |
| `sysbench` | CPU/memory sysbench workloads. | Uses sysbench CLI. |
| `unixbench` | UnixBench workloads. | Uses UnixBench CLI. |
| `geekbench` | Geekbench 6 CPU/Compute workloads. | Downloads upstream bundle. |
| `yabs` | Yet Another Benchmark Script. | Executes upstream script. |
| `phoronix_test_suite` | Virtual workloads from PTS profiles. | Workload names derived from PTS config. |

## CLI workflow

- List plugins: `lb plugin list`
- Enable a workload: `lb plugin list --enable stress_ng`
- Interactive selection: `lb plugin select`
- Enable/disable with config helpers: `lb config enable-workload <name>` / `lb config disable-workload <name>`

Note: there is no CLI install/uninstall command at the moment. Use the user plugin
directory or the Python API (`lb_plugins.api.PluginInstaller`) if you need to add
plugins programmatically.

## Configuration basics

Workloads live in the config under `workloads`:

```json
"workloads": {
  "stress_ng": {
    "plugin": "stress_ng",
    "enabled": true,
    "intensity": "user_defined",
    "options": {
      "cpu_workers": 4,
      "vm_workers": 2
    }
  }
}
```

Typed plugin settings can be stored in `plugin_settings` (Pydantic models) when working
programmatically:

```json
"plugin_settings": {
  "stress_ng": {
    "cpu_workers": 4,
    "vm_workers": 2
  }
}
```

`plugin_assets` is populated automatically by the controller from the registry and
includes any plugin-specific setup/teardown playbooks and extravars.

## Plugin interface

Plugins implement `WorkloadPlugin` from `lb_plugins.interface`.

Required members:

- `name` (string): unique identifier (matches `WorkloadConfig.plugin`).
- `description` (string): human-readable summary.
- `config_cls` (Pydantic model): config schema for plugin settings.
- `create_generator(config)`: return a workload generator instance.

`BasePluginConfig` includes `max_retries`, `timeout_buffer`, and `tags`. Extra fields
in YAML configs are ignored by default.

`WorkloadPlugin.load_config_from_file(path)` merges YAML `common` settings with
`plugins.<plugin_name>` overrides and validates using `config_cls`.

Optional members:

- `get_preset_config(level)`: return a `BasePluginConfig` for `low`, `medium`, `high`, or `user_defined`.
- `get_required_apt_packages()`, `get_required_pip_packages()`, `get_required_local_tools()`.
- `get_ansible_setup_path()`, `get_ansible_teardown_path()`.
- `get_ansible_setup_extravars()`, `get_ansible_teardown_extravars()`.
- `export_results_to_csv(results, output_dir, run_id, test_name)` to override CSV export.

`SimpleWorkloadPlugin` provides a lighter base that uses class attributes
(`NAME`, `DESCRIPTION`, `CONFIG_CLS`, `GENERATOR_CLS`, `SETUP_PLAYBOOK`, etc.).

### Generator contract

Most plugins return a `BaseGenerator` (see `lb_plugins.base_generator`). Generators
should implement `prepare()`, `start()`, `stop()`, and `cleanup()`, and return a
`generator_result` dictionary when the workload ends. The default CSV export flattens
`generator_result` into columns prefixed with `generator_`.

## Discovery and packaging

The registry resolves plugins in this order:

1. Built-ins from `lb_plugins/plugins/*/plugin.py`
2. Entry points in the `linux_benchmark.workloads` group
3. User plugins from `LB_USER_PLUGIN_DIR` or `lb_plugins/plugins/_user`

Plugins can export a single instance (`PLUGIN`), a list (`PLUGINS`), or a factory
(`get_plugins()`).

Entry point example (`pyproject.toml`):

```toml
[project.entry-points."linux_benchmark.workloads"]
my_plugin = "my_plugin.plugin:PLUGIN"
```

User plugin directory layout examples (with `LB_USER_PLUGIN_DIR=/path/to/plugins`):

- `/path/to/plugins/my_plugin.py` exporting `PLUGIN`
- `/path/to/plugins/my_plugin/plugin.py`
- `/path/to/plugins/my_plugin/pyproject.toml` with entry points

## Agent-readable plugin interface

```yaml
plugin_interface:
  required:
    name: string
    description: string
    config_cls: "pydantic.BaseModel subclass"
    create_generator: "callable(config: BasePluginConfig) -> generator"
  optional:
    get_preset_config: "callable(level: low|medium|high|user_defined) -> BasePluginConfig|None"
    get_required_apt_packages: "callable() -> list[str]"
    get_required_pip_packages: "callable() -> list[str]"
    get_required_local_tools: "callable() -> list[str]"
    get_ansible_setup_path: "callable() -> Path|None"
    get_ansible_teardown_path: "callable() -> Path|None"
    get_ansible_setup_extravars: "callable() -> dict"
    get_ansible_teardown_extravars: "callable() -> dict"
    export_results_to_csv: "callable(results, output_dir, run_id, test_name) -> list[Path]"

config_model:
  BenchmarkConfig:
    workloads: "map[str, WorkloadConfig]"
    plugin_settings: "map[str, BasePluginConfig|dict]"
    plugin_assets: "map[str, PluginAssetConfig]"
  WorkloadConfig:
    plugin: string
    enabled: bool
    intensity: "low|medium|high|user_defined"
    options: "dict"
  PluginAssetConfig:
    setup_playbook: "Path|None"
    teardown_playbook: "Path|None"
    setup_extravars: "dict"
    teardown_extravars: "dict"

discovery:
  entrypoint_group: linux_benchmark.workloads
  user_plugin_dir: "LB_USER_PLUGIN_DIR or lb_plugins/plugins/_user"
  exports: ["PLUGIN", "PLUGINS", "get_plugins()"]

results:
  default_csv: "<workload>_plugin.csv"
  base_columns:
    - run_id
    - workload
    - repetition
    - duration_seconds
    - success
  generator_fields: "generator_<key> for each key in generator_result"
```
