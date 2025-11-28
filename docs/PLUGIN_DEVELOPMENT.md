# Plugin Development Guide

This guide explains how to build, package, and install custom workload plugins for `linux-benchmark-lib`.

## Plugin anatomy
- Implement the `WorkloadPlugin` interface (`plugins/interface.py`).
- Provide a config class (usually a dataclass) and a generator derived from `workload_generators/_base_generator.py`.
- Export a module-level `PLUGIN` variable pointing to your `WorkloadPlugin` instance.

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

### Dependencies

Define your dependencies directly in the `WorkloadPlugin` class:

```python
    def get_required_apt_packages(self) -> List[str]:
        return ["some-tool"]

    def get_required_pip_packages(self) -> List[str]:
        return ["numpy"]
```

## Packaging and installation
- **Single file**: `lb plugin install /path/to/echo.py`
- **Directory**: `lb plugin install /path/to/echo_plugin_dir`
- **Archive**: `tar -czf echo.tar.gz echo_plugin_dir` then `lb plugin install echo.tar.gz`
- **Git repository**: `lb plugin install https://github.com/org/echo-plugin.git` (uses `git clone --depth 1`)
- **User drop-in**: copy `echo.py` to `~/.config/lb/plugins/`; it will be auto-discovered.
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

## Modular Plugin Structure (Recommended)

For more complex plugins that require specific Docker environments or Ansible playbooks, use the modular directory structure:

```text
plugins/<plugin_name>/
├── __init__.py
├── plugin.py       # Contains the Plugin class and Generator implementation
├── Dockerfile      # (Optional) Dedicated Docker build for this plugin
└── ansible/        # (Optional)
    ├── setup.yml
    └── teardown.yml
```

### Key Components

1.  **plugin.py**:
    *   Must define your configuration dataclass (e.g., `MyConfig`).
    *   Must define your generator class inheriting from `BaseGenerator`.
    *   Must define your plugin class inheriting from `WorkloadPlugin`.
    *   **Crucially**, must expose the plugin instance as `PLUGIN`.
    *   Implement `get_dockerfile_path()` to return `Path(__file__).parent / "Dockerfile"` if you provide one.

2.  **Dockerfile**:
    *   Define a specialized environment for your workload.
    *   The base image should align with the project's Python version if possible.
    *   Install system dependencies (e.g., `apt-get install -y coreutils`).
    *   Install the core library dependencies so the internal runner works:
        `RUN pip install --no-cache-dir psutil typer rich pyyaml InquirerPy pandas numpy jc`

3.  **__init__.py**:
    *   Can be empty, but ensures the directory is treated as a package.

### Example: `dd` Plugin

**plugins/dd/plugin.py**:
```python
from pathlib import Path
from plugins.interface import WorkloadPlugin
# ... imports ...

class DDPlugin(WorkloadPlugin):
    @property
    def name(self) -> str:
        return "dd"
    
    # ... config and generator ...

    def get_dockerfile_path(self) -> Optional[Path]:
        return Path(__file__).parent / "Dockerfile"

PLUGIN = DDPlugin()
```

**plugins/dd/Dockerfile**:
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y coreutils ...
RUN pip install --no-cache-dir psutil typer rich ...
WORKDIR /app
```

## Testing tips
- Use `PluginRegistry` in unit tests to register your plugin and create generators.
- Mock external commands the generator would execute; feed fake output to keep tests hermetic.
- For git install support, create a temporary bare repo in tests (see `tests/unit/test_plugin_installer.py`).
