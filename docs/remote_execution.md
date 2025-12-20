## Remote Execution

Remote runs are orchestrated by `lb_controller` using Ansible (install the `controller` extra). The CLI (`lb`) drives the controller through `lb_app` and runs workloads on configured hosts or provisioned targets.

### Configure remote hosts

Use `lb config init -i` to create a config and prompt for a remote host, or edit the config directly:

```json
"remote_hosts": [
  {
    "name": "node1",
    "address": "192.168.1.10",
    "user": "ubuntu",
    "become": true,
    "vars": {
      "ansible_ssh_private_key_file": "~/.ssh/id_rsa",
      "ansible_ssh_common_args": "-o StrictHostKeyChecking=no"
    }
  }
],
"remote_execution": {"enabled": true}
```

Run with:

```bash
lb run --remote
```

Use `--remote/--no-remote` to override the config for a single run (local execution is not supported by the CLI).

### Provisioned targets (dev-only)

The CLI can provision ephemeral nodes for testing:

- `lb run --docker` uses Docker/Podman containers.
- `lb run --multipass` uses Multipass VMs.

These flags are available only in dev mode (`.lb_dev_cli` or `LB_ENABLE_TEST_CLI=1`). Use `--nodes` to select how many targets to provision (max 2).

### Stop handling

You can create a stop sentinel file during a run to request a graceful stop:

```bash
lb run --stop-file /tmp/lb.stop
# touch /tmp/lb.stop to stop
```

The controller decides when cleanup is allowed; provisioned nodes are preserved if cleanup is disallowed or a failure occurs.
