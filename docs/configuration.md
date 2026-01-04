## Configuration

Runtime configuration is split between the run config (`BenchmarkConfig`) and the
platform config (`PlatformConfig`) from `lb_runner.api`.

```python
from pathlib import Path
from lb_runner.api import (
    BenchmarkConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)

config = BenchmarkConfig(
    repetitions=3,
    test_duration_seconds=120,
    metrics_interval_seconds=1.0,
    remote_hosts=[
        RemoteHostConfig(
            name="node1",
            address="192.168.1.10",
            user="ubuntu",
        )
    ],
    remote_execution=RemoteExecutionConfig(enabled=True),
    workloads={
        "stress_ng": WorkloadConfig(
            plugin="stress_ng",
            options={"cpu_workers": 4, "vm_workers": 2, "vm_bytes": "2G"},
        )
    },
)

config.save(Path("benchmark_config.json"))
config = BenchmarkConfig.load(Path("benchmark_config.json"))
```

### Notes

- `workloads` is the primary map of workload names to configuration; presence implies execution.
- `plugin_settings` can hold typed Pydantic configs for plugins; it is optional.
- `plugin_assets` is populated from the plugin registry and captures setup/teardown playbooks plus extravars.
- `output_dir`, `report_dir`, and `data_export_dir` control where artifacts are written.
- `remote_execution.enabled` controls whether the controller uses Ansible to run workloads.
- `remote_execution.upgrade_pip` toggles the pip upgrade step during global setup.
- `workloads.<name>.intensity` accepts `low`, `medium`, `high`, or `user_defined`.

### Platform vs Run Config

The configuration model is split into two files:

- **Platform config**: `~/.config/lb/platform.json`
  - Holds environment-level settings (e.g. Loki endpoint/labels, output defaults, controller defaults).
  - Includes only plugin enablement flags: `"plugins": { "dfaas": true, "fio": false }`.
  - Does **not** contain workload definitions or plugin configs.
  - Never drives execution directly.

- **Run config**: passed via `-c/--config` or `benchmark_config.json`
  - Includes `remote_hosts` and workload definitions.
  - Only workloads present in the file are considered runnable.
  - Workloads do not use an `enabled` flag; presence implies execution.
  - Experiment-specific plugin options live here (e.g. DFaaS rates/functions/iterations).

Behavioral rules:
- If a workload is present in the run config but disabled in the platform config,
  it will be skipped with a warning in the run plan.
- Provisioning choices (multipass/docker/remote) remain CLI-driven and do not
  live in the platform config.
- This is a breaking change: legacy run configs with `enabled` or platform-only
  fields must be updated to the new split.

### Plugin settings vs workloads

`workloads` drives execution and can include ad-hoc `options`. `plugin_settings` is
the typed, validated config model for a plugin. The config service will hydrate
`plugin_settings`, but does not auto-create workloads.

Example:

```json
"plugin_settings": {
  "fio": {
    "job_count": 4,
    "block_size": "4k"
  }
},
"workloads": {
  "fio": {
    "plugin": "fio"
  }
}
```
