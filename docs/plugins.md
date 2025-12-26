## Workloads and Plugins

Linux Benchmark Library exposes workloads as plugins. Built-in plugins are loaded via entry points and include:

- `stress_ng`
- `dd`
- `fio`
- `hpl`
- `stream`

Third-party plugins are installed into `lb_plugins/plugins/_user` (override with `LB_USER_PLUGIN_DIR`).

### CLI workflow

- List plugins: `lb plugin list`
- Enable a workload: `lb plugin list --enable stress_ng`
- Interactive selection: `lb plugin select`
- Install a plugin: `lb plugin install /path/to/plugin` or `lb plugin install https://github.com/...`
- Uninstall a plugin: `lb plugin uninstall <name>`

### Configuration

Workloads live in the config under `workloads`:

```json
"workloads": {
  "stress_ng": {
    "plugin": "stress_ng",
    "enabled": true,
    "options": {
      "cpu_workers": 4,
      "vm_workers": 2
    }
  }
}
```

You can also store typed plugin configs in `plugin_settings` (Pydantic models) when working programmatically.

### Plugin structure (high level)

A plugin module exports a `WorkloadPlugin` instance named `PLUGIN` and may provide:

- `config_cls` (Pydantic model for plugin settings)
- `get_required_apt_packages()`
- `create_generator()` to emit workload commands

The controller and CLI discover plugins via entry points and the user plugin directory.
