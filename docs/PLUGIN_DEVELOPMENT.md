# Plugin Development Guide

This guide explains how to build, package, and install custom workload plugins for `linux-benchmark-lib`.

## Plugin anatomy
- Implement the `WorkloadPlugin` interface (`plugins/interface.py`).
- Provide a config class (usually a dataclass) and a generator derived from `workload_generators/_base_generator.py`.
- Export a module-level `PLUGIN` variable pointing to your `WorkloadPlugin` instance.
- Optionally declare install dependencies via a manifest (`<name>.yaml`).

### Minimal example
```python
from dataclasses import dataclass, field
from typing import List, Optional, Type
from plugins.interface import WorkloadPlugin
from workload_generators._base_generator import BaseGenerator


@dataclass
class EchoConfig:
    message: str = "hello"
    extra_args: List[str] = field(default_factory=list)


class EchoGenerator(BaseGenerator):
    def __init__(self, config: EchoConfig):
        super().__init__("EchoGenerator")
        self.config = config

    def _validate_environment(self) -> bool:
        return True  # always safe

    def _run_command(self) -> None:
        # Capture a trivial result; real plugins would shell out to a tool.
        self._result = {"message": self.config.message, "args": self.config.extra_args}
        self._is_running = False

    def _stop_workload(self) -> None:
        pass


class EchoPlugin(WorkloadPlugin):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Example echo workload"

    @property
    def config_cls(self) -> Type[EchoConfig]:
        return EchoConfig

    def create_generator(self, config: EchoConfig) -> EchoGenerator:
        return EchoGenerator(config)

    def get_required_apt_packages(self) -> List[str]:
        return []  # none


PLUGIN = EchoPlugin()
```

### Manifest (dependencies)
Place a YAML file next to the plugin source to declare system/Python deps:
```yaml
name: echo
description: Example echo workload
apt_packages: []
pip_packages: []
```
These manifests are used by `tools/gen_plugin_assets.py` to update Docker/Ansible install steps.

## Packaging and installation
- **Single file**: `lb plugin install /path/to/echo.py`
- **Directory with manifest**: `lb plugin install /path/to/echo_plugin_dir`
- **Archive**: `tar -czf echo.tar.gz echo_plugin_dir` then `lb plugin install echo.tar.gz`
- **Git repository**: `lb plugin install https://github.com/org/echo-plugin.git` (uses `git clone --depth 1`)
- **User drop-in**: copy `echo.py` (and optional `echo.yaml`) to `~/.config/lb/plugins/`; it will be auto-discovered.
- **Entry point (packaged dist)**: expose `PLUGIN` via `pyproject.toml`:
  ```toml
  [project.entry-points."linux_benchmark.workloads"]
  echo = "my_pkg.echo:PLUGIN"
  ```

After installing, enable the workload in your config:
```bash
lb plugin list --enable echo
lb plugin list --select  # interactive toggle
```

To pin default options, add to `plugin_settings` or `workloads` in `benchmark_config.json`:
```json
"workloads": {"echo": {"plugin": "echo", "enabled": true, "options": {"message": "hi"}}}
```

## Regenerating dependency assets (repo contributors)
When you add or change a manifest in the main repository, run:
```bash
uv run python tools/gen_plugin_assets.py
```
Commit the updated Dockerfile block and `ansible/roles/workload_runner/tasks/plugins.generated.yml`.
User-installed plugins do not require regenerating these assets.

## Testing tips
- Use `PluginRegistry` in unit tests to register your plugin and create generators.
- Mock external commands the generator would execute; feed fake output to keep tests hermetic.
- For git install support, create a temporary bare repo in tests (see `tests/unit/test_plugin_installer.py`).
