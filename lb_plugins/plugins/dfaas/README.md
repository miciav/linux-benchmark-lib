# DFaaS Plugin

The DFaaS plugin reproduces the legacy sampling workflow using:
- OpenFaaS functions as the target workload.
- k6 for load generation.
- Prometheus + exporters for metrics.

It runs one configuration at a time, applies cooldown and overload rules, and
persists legacy-compatible CSV outputs.

## Architecture

### Component diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Controller Host                                │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐     │
│  │  DFaaS Generator │───▶│  Ansible Runner │───▶│ Prometheus Client│    │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘     │
└─────────────────────────────────┬───────────────────────┬───────────────┘
                                  │ SSH                   │ HTTP
                    ┌─────────────┴─────────────┐         │
                    ▼                           ▼         │
        ┌───────────────────┐       ┌───────────────────┐ │
        │     k6 Host       │       │   Target Host     │◀┘
        │  ┌─────────────┐  │       │  ┌─────────────┐  │
        │  │     k6      │  │──────▶│  │  OpenFaaS   │  │
        │  └─────────────┘  │ HTTP  │  │   Gateway   │  │
        │                   │       │  └─────────────┘  │
        └───────────────────┘       │  ┌─────────────┐  │
                                    │  │ Prometheus  │  │
                                    │  │ + exporters │  │
                                    │  └─────────────┘  │
                                    │  ┌─────────────┐  │
                                    │  │    k3s      │  │
                                    │  └─────────────┘  │
                                    └───────────────────┘
```

### Components

**Controller host** (where the runner executes):
- Runs the DFaaS generator locally.
- Invokes Ansible to provision the target and k6 hosts.
- Pulls k6 summaries via Ansible fetch.
- Queries Prometheus over HTTP.

**Target host**:
- Runs k3s + OpenFaaS + Prometheus + node-exporter + cAdvisor.
- Exposes the OpenFaaS gateway (NodePort 31112) and Prometheus (NodePort 30411).

**k6 host**:
- Receives k6 scripts via Ansible.
- Runs k6 and exports a summary.json file.

### Repository layout

- `plugin.py`: config schema and CSV export.
- `generator.py`: config generation, k6 orchestration, Prometheus queries.
- `queries.yml`: PromQL queries.
- `ansible/`: setup and run playbooks.
  - `setup_target.yml` installs k3s/OpenFaaS/Prometheus stack (target-only; does not install k6).
  - `setup_plugin.yml` orchestrates both target and k6 host setup.
  - `setup_k6.yml` installs k6 and prepares workspace.
  - `run_k6.yml` runs a single config on the k6 host.
- `ansible/manifests/`: Kubernetes manifests for Prometheus and exporters.

## Prerequisites

### Software requirements

**Controller host**:
- Python 3.12+
- `ansible-playbook` (Ansible Core 2.15+)
- `faas-cli` (OpenFaaS CLI)
- SSH client with key-based authentication

**Target host**:
- Ubuntu 22.04+ or Debian 12+ (systemd-based)
- Minimum 4 GB RAM, 2 CPUs
- Root/sudo access
- Ports 31112 (OpenFaaS) and 30411 (Prometheus) available

**k6 host**:
- Ubuntu 22.04+ or Debian 12+
- Minimum 2 GB RAM, 2 CPUs
- Root/sudo access

### Network requirements

Required connectivity:
- Controller -> target: SSH (port 22), HTTP to Prometheus (port 30411)
- Controller -> k6 host: SSH (port 22)
- k6 host -> target: HTTP to OpenFaaS gateway (port 31112)

Default ports:
- OpenFaaS gateway: 31112 (NodePort)
- Prometheus: 30411 (NodePort)

If NodePorts are not reachable from the controller, use SSH tunneling:
```bash
ssh -L 30411:localhost:30411 -L 31112:localhost:31112 user@target-host
```

## Setup steps

### Step 1: Prepare SSH access

Ensure passwordless SSH access from controller to both target and k6 hosts:
```bash
ssh-copy-id user@target-host
ssh-copy-id user@k6-host
```

### Step 2: Create inventory files

**Target inventory** (`target_inventory.ini`):
```ini
[all]
target ansible_host=<target-ip> ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/id_rsa
```

**k6 inventory** (`k6_inventory.ini`):
```ini
[all]
k6 ansible_host=<k6-ip> ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/id_rsa
```

### Step 3: Setup target host (k3s + OpenFaaS + Prometheus)

```bash
ansible-playbook -i target_inventory.ini \
  -e '{"openfaas_functions":["figlet","env"]}' \
  lb_plugins/plugins/dfaas/ansible/setup_target.yml
```
Note: `setup_target.yml` does not install k6.

Key variables:
- `openfaas_gateway_node_port` (default 31112)
- `openfaas_functions` (list of store functions to deploy)
- `prometheus_node_port` (default 30411)
- `scaphandre_enabled` + `scaphandre_repo_url` + `scaphandre_chart` for power metrics

Verification:
```bash
ssh target-host kubectl get nodes
faas-cli list --gateway http://<target-ip>:31112
curl http://<target-ip>:30411/-/ready
```

To provision both the target and k6 hosts in one go, run:
```bash
ansible-playbook -i target_inventory.ini \
  -e "benchmark_config=<path-to-benchmark-config>" \
  lb_plugins/plugins/dfaas/ansible/setup_plugin.yml
```

### Step 4: Setup k6 host

```bash
ansible-playbook -i k6_inventory.ini lb_plugins/plugins/dfaas/ansible/setup_k6.yml
```

Key variables:
- `k6_workspace_root` (default `/home/<k6_user>/.dfaas-k6`)
- `k6_version` (default `0.49.0`)

Verification:
```bash
ssh k6-host k6 version
```

### Step 5: Create benchmark configuration

Create a YAML configuration file (see Configuration reference below) or use the example config.

## Run flow

### Execution sequence

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DFaaS Generator Run Flow                         │
├─────────────────────────────────────────────────────────────────────────┤
│  1. Load configuration                                                   │
│     └─▶ Parse YAML/JSON config, validate settings                       │
│                                                                          │
│  2. Generate configurations                                              │
│     └─▶ Build function combinations × rate permutations                 │
│                                                                          │
│  3. Load existing index (for resume support)                            │
│     └─▶ Skip already-completed configurations                           │
│                                                                          │
│  4. Measure baseline idle metrics                                        │
│     └─▶ Query Prometheus for CPU/RAM/power at rest                      │
│                                                                          │
│  5. For each configuration:                                              │
│     ├─▶ Check dominance (skip if dominated by overloaded config)        │
│     ├─▶ Wait for cooldown (CPU/RAM below threshold, replicas < 2)       │
│     ├─▶ Generate k6 script for this config                              │
│     ├─▶ Execute k6 via Ansible on k6 host                               │
│     ├─▶ Parse k6 summary (success rate, latency)                        │
│     ├─▶ Query Prometheus for metrics                                    │
│     ├─▶ Evaluate overload conditions                                    │
│     ├─▶ Record results to CSV                                           │
│     └─▶ Update index                                                    │
│                                                                          │
│  6. Finalize outputs                                                     │
│     └─▶ Write results.csv, skipped.csv, index.csv                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### Configuration generation logic

1. Build a global rate list from `min_rate..max_rate` inclusive.
2. Apply `functions[].max_rate` (if set) to cap rates per function.
3. Generate function combinations from `min_functions` to `max_functions` (exclusive).
4. Produce all rate permutations for each combination.

### Dominance rules

Config B dominates A when:
- Same function set
- All rates are greater or equal
- At least one rate is strictly greater

If A is overloaded, all dominant configs are skipped.

### Cooldown rules

Wait until:
- CPU/RAM/POWER are within `idle_threshold_pct` of idle values
- Function replicas < 2

Timeout at `max_wait_seconds`.

### Overload detection

**Node overloaded** if:
- Average success rate < `success_rate_node_min`
- CPU > `cpu_overload_pct_of_capacity`
- RAM > `ram_overload_pct`
- Any function is overloaded

**Function overloaded** if:
- Success rate < `success_rate_function_min`
- Replica count >= `replicas_overload_threshold`

### Running via controller

The plugin can be run via the controller or directly via a BenchmarkConfig.

Configuration is typically supplied via:
- `config_path`: YAML/JSON file with `common` and `plugins.dfaas`.
- or `options` in `user_defined` mode.

Config precedence:
1. `common` in the file.
2. `plugins.dfaas` in the file.
3. Options passed alongside `config_path` (highest priority).

## Configuration reference

All fields live under `plugins.dfaas` unless noted.

### Core
- `config_path` (Path, optional): YAML/JSON file with `common` + `plugins.dfaas`.
- `output_dir` (Path, optional): override output directory for artifacts.
- `run_id` (str, optional): identifier for the k6 workspace path.

### k6 host
- `k6_host` (str, default `127.0.0.1`): k6 host address.
- `k6_user` (str, default `ubuntu`): SSH user for k6 host.
- `k6_ssh_key` (str, default `~/.ssh/id_rsa`): SSH private key.
- `k6_port` (int, default 22): SSH port.
- `k6_workspace_root` (str, default `/home/<k6_user>/.dfaas-k6`): workspace root on k6 host.
- `k6_outputs` (list[str], default empty): optional k6 `--out` targets (e.g. Loki).
- `k6_tags` (map, default empty): additional k6 tags merged with run metadata.

### OpenFaaS and Prometheus
- `gateway_url` (str, default `http://127.0.0.1:31112`): OpenFaaS gateway URL.
- `prometheus_url` (str, default `http://127.0.0.1:30411`): Prometheus base URL. For multi-host Grafana provisioning, use a template like `http://{host.address}:30411`.

### Grafana (optional)
- `grafana.enabled` (bool, default false): enable Grafana integration.
- `grafana.url` (str, default `http://localhost:3000`): Grafana base URL.
- `grafana.api_key` (str, optional): API key for provisioning datasource/dashboard.
- `grafana.org_id` (int, default 1): Grafana org id.

### Functions
List of function objects:
- `name` (str, required): OpenFaaS function name.
- `method` (str, default `GET`): HTTP method.
- `body` (str, default empty): request body.
- `headers` (map, default empty): HTTP headers.
- `max_rate` (int, optional): per-function max rate; caps global rates.

Validation:
- Function names must be unique.
- If `max_rate` is set, it must be >= `rates.min_rate`.

### Rates
- `rates.min_rate` (int, default 0): inclusive min requests/sec.
- `rates.max_rate` (int, default 200): inclusive max requests/sec.
- `rates.step` (int, default 10): step size.

### Combinations
- `combinations.min_functions` (int, default 1): minimum functions per config.
- `combinations.max_functions` (int, default 2): exclusive upper bound.

### Timing
- `duration` (str, default `30s`): k6 duration.
- `iterations` (int, default 3): iterations per config.

### Cooldown
- `cooldown.max_wait_seconds` (int, default 180).
- `cooldown.sleep_step_seconds` (int, default 5).
- `cooldown.idle_threshold_pct` (float, default 15).

### Overload thresholds
- `overload.cpu_overload_pct_of_capacity` (float, default 80).
- `overload.ram_overload_pct` (float, default 90).
- `overload.success_rate_node_min` (float, default 0.95).
- `overload.success_rate_function_min` (float, default 0.90).
- `overload.replicas_overload_threshold` (int, default 15).

### Metrics and queries
- `queries_path` (str, default `lb_plugins/plugins/dfaas/queries.yml`).
- `scaphandre_enabled` (bool, default false).
- `function_pid_regexes` (map, default empty): PID regex per function for power.

### Deployment hints
- `deploy_functions` (bool, default true): informational flag.
  The setup playbook actually uses the `openfaas_functions` extra var.

### Example config (YAML)

```yaml
common:
  timeout_buffer: 10

plugins:
  dfaas:
    k6_host: "10.0.0.50"
    k6_user: "ubuntu"
    k6_ssh_key: "~/.ssh/id_rsa"
    k6_port: 22

    gateway_url: "http://<target-ip>:31112"
    prometheus_url: "http://<target-ip>:30411"
    k6_outputs:
      - "loki=http://<controller-ip>:3100/loki/api/v1/push"
    k6_tags:
      environment: "lab"
    grafana:
      enabled: true
      url: "http://<controller-ip>:3000"
      api_key: "<grafana_api_key>"

    functions:
      - name: "figlet"
        method: "POST"
        body: "Hello DFaaS!"
        headers:
          Content-Type: "text/plain"
        max_rate: 100
      - name: "env"
        method: "GET"
        body: ""

    rates:
      min_rate: 0
      max_rate: 200
      step: 10

    combinations:
      min_functions: 1
      max_functions: 2

    duration: "30s"
    iterations: 3

    cooldown:
      max_wait_seconds: 180
      sleep_step_seconds: 5
      idle_threshold_pct: 15

    overload:
      cpu_overload_pct_of_capacity: 80
      ram_overload_pct: 90
      success_rate_node_min: 0.95
      success_rate_function_min: 0.90
      replicas_overload_threshold: 15

    queries_path: "lb_plugins/plugins/dfaas/queries.yml"
    deploy_functions: true
    scaphandre_enabled: false
```

## Outputs

The generator emits results into the DFaaS output directory, resolved as:
- `output_dir` if set in the config.
- otherwise `<benchmark_results>/<workload_name>`, derived from the runner.

### Artifact files

| File | Description |
|------|-------------|
| `results.csv` | One row per config iteration with all metrics |
| `skipped.csv` | Configs skipped (dominance or already executed) |
| `index.csv` | Unique configurations for resume support |
| `summaries/*.json` | Raw k6 summary output per config |
| `metrics/*.csv` | Metrics snapshot per config |
| `k6_scripts/*.js` | Generated k6 scripts |

### Column conventions in `results.csv`

**Per-function columns**:
- `function_<name>`: function name
- `rate_function_<name>`: configured rate
- `success_rate_function_<name>`: k6 success rate
- `cpu_usage_function_<name>`: CPU from cAdvisor
- `ram_usage_function_<name>`: RAM from cAdvisor
- `power_usage_function_<name>`: power from Scaphandre (if enabled)
- `replica_<name>`: replica count
- `overloaded_function_<name>`: 0 or 1
- `medium_latency_function_<name>`: average latency in ms

**Node columns**:
- `cpu_usage_idle_node`: baseline CPU
- `cpu_usage_node`: CPU during test
- `ram_usage_idle_node`: baseline RAM
- `ram_usage_node`: RAM during test
- `ram_usage_idle_node_percentage`: baseline RAM %
- `ram_usage_node_percentage`: RAM % during test
- `power_usage_idle_node`: baseline power
- `power_usage_node`: power during test
- `rest_seconds`: cooldown wait time
- `overloaded_node`: 0 or 1

### Metrics collected

Prometheus queries are defined in `queries.yml` and include:
- Node CPU usage (from node-exporter)
- Node RAM usage (from node-exporter)
- Function CPU and RAM usage (from cAdvisor)
- Power metrics if Scaphandre is enabled

If a query fails, the metric is recorded as `nan`.

## Troubleshooting

### Common issues

| Issue | Possible cause | Solution |
|-------|---------------|----------|
| OpenFaaS gateway unreachable | NodePort not exposed or firewall | Verify port 31112 is open; check `kubectl get svc -n openfaas` |
| `faas-cli login` fails | Wrong password or gateway URL | Run `kubectl get secret -n openfaas basic-auth -o jsonpath="{.data.basic-auth-password}" \| base64 -d` |
| Prometheus timeouts | Pod not running or wrong port | Check `kubectl get pods -n openfaas -l app=prometheus` |
| k6 SSH errors | Key permissions or network | Verify key has 600 permissions; test `ssh -i key user@host` |
| Cooldown never finishes | High CPU/RAM or stuck replicas | Check `faas-cli list` for replica counts; investigate load source |
| Missing metrics in results | Exporter pods not running | Verify `node-exporter` and `cadvisor` daemonsets are healthy |
| `nan` values in CSV | Prometheus query returned empty | Check Prometheus targets are UP at `http://<target>:30411/targets` |

### Diagnostic commands

```bash
# Check k3s cluster status
ssh target-host kubectl get nodes

# Check OpenFaaS pods
ssh target-host kubectl get pods -n openfaas

# Check Prometheus targets
curl http://<target-ip>:30411/api/v1/targets | jq '.data.activeTargets[].health'

# Test function invocation
curl -X POST http://<target-ip>:31112/function/figlet -d "test"

# Check k6 installation
ssh k6-host k6 version

# View k6 workspace
ssh k6-host ls -la /home/<k6_user>/.dfaas-k6/
```

### Debug mode

Set environment variable for verbose logging:
```bash
export LB_LOG_LEVEL=DEBUG
```

## Testing

- Unit tests: `tests/unit/lb_plugins/test_dfaas_*`
- Docker integration: `tests/integration/lb_plugins/test_dfaas_docker_integration.py`
- Multipass e2e: `tests/e2e/test_dfaas_multipass_e2e.py` (creates two VMs)

Run unit tests:
```bash
uv run pytest tests/unit/lb_plugins/test_dfaas*.py -v
```

## Extending the plugin

- Add functions by updating `functions` and (optionally) `openfaas_functions`.
- Cap per-function rate with `functions[].max_rate`.
- Add new rate generation strategies by extending
  `generate_configurations` and adding new config fields.
