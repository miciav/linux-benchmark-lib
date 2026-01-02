# DFaaS-2: Generator orchestration (k6, single-config loop, cooldown, dominance)

## Context
We need a DFaaS generator that runs one configuration at a time, waits for cooldown, evaluates overload, and skips dominant configurations. k6 runs on a separate host. No core changes.

## Goal
Implement generator logic that:
- creates one k6 script per configuration
- runs k6 via Ansible on the k6-host
- collects summary + Prometheus metrics
- applies cooldown/overload/dominance rules
- emits CSV outputs (results, skipped, index)

## Scope
- Generator implementation only.
- No Ansible playbooks (DFaaS-3/4).

## Execution flow (must match legacy)
1) Build configs (functions x rates) per combination.
2) For each config:
   - If dominated by `actual_dominant_config`, skip.
   - If already in `index.csv`, skip.
   - For each iteration:
     - Wait for cooldown (legacy rules).
     - Generate k6 script for this config.
     - Run k6 via Ansible (block until finish).
     - Parse summary for success/latency.
     - Query Prometheus for CPU/RAM/power.
     - Compute overload.
     - Append CSV row.
     - If overloaded > iterations/2, set `actual_dominant_config`.
     - Write `index.csv`.

## Partial objectives + tests
### Objective 1: Config enumeration
- Implement config generation (combinations + rate product).
**Tests**
- Unit test: 2 functions, rates [0,10], expect 4 configs.
- Unit test: dominance function returns true for non-decreasing rates.

### Objective 2: Single-config k6 script generation
- Generate a JS script for one config (functions + rates + duration).
- Tag each request by function name.
**Tests**
- Unit test: script contains expected URLs and tags.
- Manual test: run script locally with k6 (no OpenFaaS) against dummy HTTP server.

### Objective 3: Ansible-run k6 invocation
- Generator calls playbook with inputs: target name, run_id, config_id, script path.
- Block until k6 finishes.
**Tests**
- Manual test: `k6 version` is available and summary.json produced.
- Manual test: run on k6-host without OpenFaaS by pointing to `httpbin`.

### Objective 4: Summary parsing
- Parse `summary.json` into per-function success rate + mean latency.
**Tests**
- Unit test: parser extracts metrics from a fixture summary JSON.

### Objective 5: Cooldown + overload
- Implement cooldown checks (CPU/RAM/power + replicas < 2).
- Implement overload rules (legacy).
**Tests**
- Unit test: overload returns true when success rate < threshold.
- Manual test: force overload by high rate, verify skip of dominant configs.

### Objective 6: CSV outputs
- `results.csv`, `skipped.csv`, `index.csv` match legacy header style.
**Tests**
- Unit test: headers stable and include per-function columns.
- Manual test: verify config ids match CSV entries.

## Acceptance criteria
- One config at a time.
- Cooldown + overload behavior matches legacy.
- Dominant configs skipped.
- Summary parsed and CSVs produced.

## Dependencies
- DFaaS-1 (config schema)
- DFaaS-4 (k6 host run playbook)
- DFaaS-5 (Prometheus queries)

