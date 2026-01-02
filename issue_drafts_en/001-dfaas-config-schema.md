# DFaaS-1: Define DFaaS config schema + legacy rules (cooldown/overload/dominance)

## Context
We need a DFaaS workload plugin for linux-benchmark-lib that reproduces the legacy sampling logic from `metrics_predictions/samples_generator`. The config must be file-based (YAML/JSON) and overridable via `options` (user_defined), without modifying the core library.

## Goal
Define a complete, validated DFaaS configuration schema and formalize the legacy rules for:
- function combinations
- rate lists
- cooldown
- overload detection
- dominance-based skipping

## Scope
- Pydantic config model (fields, defaults, validation).
- Merge behavior: `config_path` (common + plugins.dfaas) + `options` override.
- Formal rules documented (deterministic, testable).

## Non-scope
- Plugin implementation or Ansible playbooks (covered by later issues).

## Proposed config (YAML)
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
    prometheus_url: "http://<target-ip>:9090"

    functions:
      - name: "figlet"
        method: "POST"
        body: "Hello DFaaS!"
        headers:
          Content-Type: "text/plain"
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
```

## Formal rules
### Rate list
- `rates = [min_rate..max_rate step]` (inclusive)
- Sorted ascending

### Function combinations
- Use `min_functions..max_functions` (max exclusive), legacy behavior
- For each combination, compute cartesian product of rates per function

### Dominance (new)
- B dominates A if for all functions `rate_B >= rate_A` and for at least one function `rate_B > rate_A`.
- If A is overloaded, skip any later configuration dominated by A.

### Cooldown (legacy)
- Must satisfy: CPU, RAM, POWER <= idle + idle * 15% AND replicas < 2
- Max wait 180s, otherwise abort run

### Overload (legacy)
- Node overloaded if:
  - avg success rate < 0.95 OR
  - CPU > 80% capacity OR
  - RAM > 90% OR
  - any function overloaded
- Function overloaded if:
  - success rate < 0.90 OR
  - replicas >= 15

## Partial objectives + tests
### Objective 1: Config model + validation
- Define `DfaasConfig` (Pydantic), including nested structures.
- Validate duration format, iterations > 0, rate bounds.
**Tests**
- Unit test: valid config loads successfully.
- Unit test: invalid config (min_rate > max_rate) raises validation error.
- Unit test: invalid duration format rejected.

### Objective 2: Merge behavior (file + options)
- Load from config file (`common` + `plugins.dfaas`).
- Apply `options` overrides last.
**Tests**
- Unit test: override `rates.max_rate` via options and assert final value.
- Unit test: missing fields get defaults.

### Objective 3: Formal rules documented
- Document dominance, cooldown, overload in a single spec block.
**Tests**
- Manual review checklist: rules text matches legacy in `samples_generator`.

## Acceptance criteria
- Schema documented with defaults and constraints.
- Merge behavior clearly defined.
- Legacy rules captured verbatim with new dominance definition.

## Dependencies
- Blocks DFaaS-2 (generator).

