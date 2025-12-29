# DFaaS Plugin

This plugin implements the legacy DFaaS sampling workflow using k6 on a
dedicated host and OpenFaaS/Prometheus on the target.

## Architecture
- Target host: runner + k3s + OpenFaaS + Prometheus + exporters.
- k6 host: executes load, controlled via SSH from the target host.
- Network paths:
  - target -> k6-host over SSH (port 22 by default)
  - k6-host -> OpenFaaS gateway (port 31112 by default)
  - target -> Prometheus (NodePort 30411 by default)

## Prerequisites
- SSH access from target host to k6 host using the configured key.
- Target host packages: `kubectl`, `helm`, `faas-cli`, `ansible-playbook`.
- Open ports: 22 (SSH), 31112 (OpenFaaS gateway), 30411 (Prometheus).

## Setup steps
1. Install k6 on the k6 host:
   - Run `lb_plugins/plugins/dfaas/ansible/setup_k6.yml` against the k6 host.
2. Install k3s/OpenFaaS/Prometheus on the target host:
   - Run `lb_plugins/plugins/dfaas/ansible/setup_target.yml` against the target.
3. Verify:
   - `kubectl get nodes` shows Ready.
   - `faas-cli list --gateway http://<target>:31112` lists functions.
   - `curl http://<target>:30411/-/ready` returns 200.

## Run flow
- Generate all function combinations and rate vectors.
- For each config:
  - Enforce cooldown (idle CPU/RAM/POWER and replicas < 2).
  - Generate a k6 script and run it on the k6 host.
  - Parse the k6 summary and query Prometheus.
  - Compute overload and skip dominant configs when needed.

## Outputs
In the workload output directory:
- `results.csv`, `skipped.csv`, `index.csv` (legacy-compatible headers).
- `summaries/summary-<config>-iter<iter>-rep<rep>.json`
- `metrics/metrics-<config>-iter<iter>-rep<rep>.csv`
- `k6_scripts/config-<config>.js`

## Config loading
- `config_path` can be passed via workload options to load a YAML/JSON file that
  contains `common` and `plugins.dfaas` sections.
- `plugins.dfaas` overrides `common`, and any options passed alongside
  `config_path` override both.

## Config schema
Top-level fields (in `plugins.dfaas`):
- `k6_host` (str): k6 host address.
- `k6_user` (str): SSH user for the k6 host.
- `k6_ssh_key` (str): SSH private key path.
- `k6_port` (int): SSH port.
- `k6_workspace_root` (str): workspace root on the k6 host.
- `output_dir` (str): optional output directory override for DFaaS artifacts.
- `run_id` (str): optional run identifier used for k6 workspace.
- `gateway_url` (str): OpenFaaS gateway URL.
- `prometheus_url` (str): Prometheus base URL (default NodePort 30411).
- `functions` (list): list of function objects (name/method/body/headers/max_rate).
- `rates` (object): `min_rate`, `max_rate`, `step`.
- `combinations` (object): `min_functions`, `max_functions` (max is exclusive).
- `duration` (str): k6 duration string (e.g. `30s`).
- `iterations` (int): iterations per configuration.
- `cooldown` (object): `max_wait_seconds`, `sleep_step_seconds`,
  `idle_threshold_pct`.
- `overload` (object): `cpu_overload_pct_of_capacity`, `ram_overload_pct`,
  `success_rate_node_min`, `success_rate_function_min`,
  `replicas_overload_threshold`.
- `queries_path` (str): path to the Prometheus queries file.
- `deploy_functions` (bool): deploy OpenFaaS store functions.
- `scaphandre_enabled` (bool): enable power metrics via Scaphandre.
- `function_pid_regexes` (map): optional PID regex per function when Scaphandre is enabled.

Common base fields:
- `max_retries` (int): retries for the workload (default 0).
- `timeout_buffer` (int): safety buffer added to expected runtime (default 10).
- `tags` (list[str]): workload tags.

Function object fields:
- `name` (str): OpenFaaS function name.
- `method` (str): HTTP method (GET/POST/etc).
- `body` (str): request payload (match legacy payloads in
  `legacy_materials/samples_generator/utils.py`).
- `headers` (map): HTTP headers.
- `max_rate` (int, optional): per-function maximum rate (requests/sec).

## Example config (YAML)
```
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
      - name: "eat-memory"
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

## Formal rules (legacy)
- Rate list: `rates = [min_rate..max_rate step]` inclusive, ascending.
- Combinations: function sets from `min_functions..max_functions` (max exclusive).
- Dominance: Config B dominates A if for every function `rate_B >= rate_A` and
  for at least one function `rate_B > rate_A`. If A is overloaded, skip all
  dominant configs.
- Cooldown: wait until CPU/RAM/POWER <= idle + idle * 15% and replicas < 2, with
  a max wait of 180s.
- Overload:
  - Node overloaded if avg success rate < 0.95 OR CPU > 80% capacity OR
    RAM > 90% OR any function overload.
  - Function overloaded if success rate < 0.90 OR replicas >= 15.

## Troubleshooting
- OpenFaaS gateway unreachable: confirm NodePort 31112 and `faas-cli login`.
- Prometheus query timeouts: verify `prometheus_url` and NodePort 30411.
- k6 SSH failures: confirm `k6_host`, `k6_user`, and `k6_ssh_key` are correct.
- Cooldown never completes: check for stuck replicas or sustained CPU/RAM load.
