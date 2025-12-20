## Quick Start

### CLI

```bash
# Create a config and prompt for a remote host
lb config init -i

# Enable a workload
lb plugin list --enable stress_ng

# Run remotely (uses the config's remote hosts)
lb run --remote --run-id demo-run
```

Dev-only provisioning (requires `.lb_dev_cli` or `LB_ENABLE_TEST_CLI=1`):

```bash
LB_ENABLE_TEST_CLI=1 lb run --docker --run-id demo-docker
```

### Python API (Controller)

```python
from lb_controller.api import (
    BenchmarkConfig,
    BenchmarkController,
    RemoteExecutionConfig,
    RemoteHostConfig,
)

config = BenchmarkConfig(
    repetitions=2,
    remote_hosts=[
        RemoteHostConfig(name="node1", address="192.168.1.10", user="ubuntu")
    ],
    remote_execution=RemoteExecutionConfig(enabled=True),
)

controller = BenchmarkController(config)
summary = controller.run(["stress_ng"], run_id="demo-run")
print(summary.per_host_output)
```

For runner-only integrations, use `lb_runner.api` and `lb_runner.local_runner.LocalRunner`.
