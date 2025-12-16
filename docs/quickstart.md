## Quick Start

```python
from lb_runner.benchmark_config import BenchmarkConfig, RemoteHostConfig, RemoteExecutionConfig
from lb_controller.controller import BenchmarkController
from lb_runner.local_runner import LocalRunner
from lb_runner.plugin_system.builtin import builtin_plugins
from lb_runner.plugin_system.registry import PluginRegistry

# Create a configuration
config = BenchmarkConfig(
    repetitions=3,
    test_duration_seconds=3600,
    metrics_interval_seconds=1.0
)

# Local execution (Agent Mode)
registry = PluginRegistry(builtin_plugins())
runner = LocalRunner(config, registry=registry)
runner.run_benchmark("stress_ng")

# Remote execution (Controller Mode)
# Requires 'controller' extra installed
remote_config = BenchmarkConfig(
    remote_hosts=[RemoteHostConfig(name="node1", address="192.168.1.10", user="ubuntu")],
    remote_execution=RemoteExecutionConfig(enabled=True),
)
# Use distinct, non-empty `name` values per host; they become per-host output dirs.
controller = BenchmarkController(remote_config)
summary = controller.run(["stress_ng"], run_id="demo-run")
print(summary.per_host_output)
```