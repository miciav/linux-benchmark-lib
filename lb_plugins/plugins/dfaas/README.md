# DFaaS Plugin

The DFaaS plugin reproduces the legacy sampling workflow using:
- OpenFaaS functions as the target workload.
- k6 for load generation.
- Prometheus + exporters for metrics.

It runs one configuration at a time, applies cooldown and overload rules, and
persists legacy-compatible CSV outputs.

## Components and data flow
Control plane (where the runner executes):
- Runs the DFaaS generator locally.
- Invokes Ansible to provision the target and k6 hosts.
- Pulls k6 summaries via Ansible fetch.
- Queries Prometheus over HTTP.

Target host:
- Runs k3s + OpenFaaS + Prometheus + node-exporter + cAdvisor.
- Exposes the OpenFaaS gateway (NodePort 31112) and Prometheus (NodePort 30411).

k6 host:
- Receives k6 scripts via Ansible.
- Runs k6 and exports a summary.json file.

End-to-end flow:
1. Generate function/rate configurations.
2. Cooldown until node is idle and replicas are low.
3. Run k6 for the configuration.
4. Query Prometheus for node and function metrics.
5. Apply overload and dominance rules.
6. Emit CSVs and per-config artifacts.

## Repository layout
- `plugin.py`: config schema and CSV export.
- `generator.py`: config generation, k6 orchestration, Prometheus queries.
- `queries.yml`: PromQL queries.
- `ansible/`: setup and run playbooks.
  - `setup_target.yml` installs k3s/OpenFaaS/Prometheus stack.
  - `setup_k6.yml` installs k6 and prepares workspace.
  - `run_k6.yml` runs a single config on the k6 host.
- `legacy_materials/`: reference artifacts from the legacy workflow.

## Network and ports
Required connectivity:
- Controller -> target: SSH (for Ansible), HTTP to Prometheus.
- Controller -> k6 host: SSH (for Ansible).
- k6 host -> OpenFaaS gateway: HTTP.

Default ports:
- OpenFaaS gateway: 31112 (NodePort).
- Prometheus: 30411 (NodePort).

If NodePorts are not reachable from the controller, use SSH tunneling.

## Setup (manual or via controller)

### k6 host
Playbook: `lb_plugins/plugins/dfaas/ansible/setup_k6.yml`

Example:
```bash
ansible-playbook -i k6_inventory.ini lb_plugins/plugins/dfaas/ansible/setup_k6.yml
```

Key variables:
- `k6_workspace_root` (default `/var/lib/dfaas-k6`).
- `k6_version` (default `0.49.0`).

Verification:
```bash
ssh <k6-host> k6 version
```

### target host (k3s + OpenFaaS + Prometheus)
Playbook: `lb_plugins/plugins/dfaas/ansible/setup_target.yml`

Example:
```bash
ansible-playbook -i target_inventory.ini \
  -e '{"openfaas_functions":["figlet","env"]}' \
  lb_plugins/plugins/dfaas/ansible/setup_target.yml
```

Notes:
- OpenFaaS is installed via Helm.
- OpenFaaS built-in Prometheus/Alertmanager are disabled; a dedicated Prometheus
  deployment is applied from `legacy_materials/infrastructure/` plus custom
  manifests.

Key variables:
- `openfaas_gateway_node_port` (default 31112).
- `openfaas_functions` (list of store functions to deploy).
- `prometheus_node_port` (default 30411).
- `scaphandre_enabled` + `scaphandre_repo_url` + `scaphandre_chart` for power metrics.

Verification:
```bash
kubectl get nodes
faas-cli list --gateway http://<target-ip>:31112
curl http://<target-ip>:30411/-/ready
```

## Running the workload
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
- `k6_workspace_root` (str, default `/var/lib/dfaas-k6`): workspace root on k6 host.

### OpenFaaS and Prometheus
- `gateway_url` (str, default `http://127.0.0.1:31112`): OpenFaaS gateway URL.
- `prometheus_url` (str, default `http://127.0.0.1:30411`): Prometheus base URL.

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

## Example config (YAML)
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

## Configuration generation logic
1. Build a global rate list from `min_rate..max_rate` inclusive.
2. Apply `functions[].max_rate` (if set) to cap rates per function.
3. Generate function combinations from `min_functions` to `max_functions` (exclusive).
4. Produce all rate permutations for each combination.

Dominance:
- Config B dominates A when it has the same function set and all rates are
  greater or equal, with at least one strictly greater.
- If A is overloaded, all dominant configs are skipped.

Cooldown:
- Wait until CPU/RAM/POWER are within `idle_threshold_pct` of idle values and
  replicas < 2, or time out at `max_wait_seconds`.

Overload:
- Node overloaded if average success rate < threshold, or CPU/RAM exceed limits,
  or any function is overloaded.
- Function overloaded if success rate < threshold or replica count is high.

## Metrics collected
Prometheus queries are defined in `queries.yml` and include:
- Node CPU usage (from node-exporter).
- Node RAM usage (from node-exporter).
- Function CPU and RAM usage (from cAdvisor).
- Power metrics if Scaphandre is enabled.

If a query fails, the metric is recorded as `nan`.

## Outputs and artifact layout
The generator emits results into the DFaaS output directory, resolved as:
- `output_dir` if set in the config.
- otherwise `<benchmark_results>/<workload_name>`, derived from the runner.

Artifacts:
- `results.csv`: one row per config iteration.
- `skipped.csv`: configs that were skipped (dominance or already executed).
- `index.csv`: unique configurations for resume support.
- `summaries/summary-<config>-iter<iter>-rep<rep>.json`: k6 summary output.
- `metrics/metrics-<config>-iter<iter>-rep<rep>.csv`: metrics snapshot.
- `k6_scripts/config-<config>.js`: generated k6 scripts.

Column conventions in `results.csv`:
- Per-function columns: `function_<name>`, `rate_function_<name>`,
  `success_rate_function_<name>`, `cpu_usage_function_<name>`,
  `ram_usage_function_<name>`, `power_usage_function_<name>`,
  `replica_<name>`, `overloaded_function_<name>`, `medium_latency_function_<name>`.
- Node columns: `cpu_usage_idle_node`, `cpu_usage_node`, `ram_usage_idle_node`,
  `ram_usage_node`, `ram_usage_idle_node_percentage`, `ram_usage_node_percentage`,
  `power_usage_idle_node`, `power_usage_node`, `rest_seconds`, `overloaded_node`.

## Troubleshooting
- OpenFaaS gateway unreachable: verify NodePort 31112 and `faas-cli login`.
- Prometheus timeouts: verify NodePort 30411 and that node-exporter/cAdvisor pods
  are running.
- k6 SSH errors: verify `k6_host`, user, key, and network access from controller.
- Cooldown never finishes: check replicas or sustained CPU/RAM load.
- Missing metrics: confirm exporters are running and that Prometheus targets are up.

## Testing
- Unit tests: `tests/unit/lb_plugins/test_dfaas_*`.
- Docker integration: `tests/integration/lb_plugins/test_dfaas_docker_integration.py`.
- Multipass e2e: `tests/e2e/test_dfaas_multipass_e2e.py` (creates two VMs).

## Extending the plugin
- Add functions by updating `functions` and (optionally) `openfaas_functions`.
- Cap per-function rate with `functions[].max_rate`.
- Add new rate generation strategies by extending
  `generate_configurations` and adding new config fields.
