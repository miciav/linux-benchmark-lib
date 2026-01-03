# DFaaS-5: Prometheus queries (queries.yml) + metrics collection

## Context
Metrics collection must match legacy `samples_generator/utils.py`. Queries should live in `queries.yml` under the DFaaS plugin and be parameterized.

## Goal
- Create `queries.yml` with the legacy PromQL queries.
- Implement a query runner with range/instant support and retry.
- Output CSV metrics per config/iteration.

## Partial objectives + tests
### Objective 1: queries.yml definition
- Encode legacy queries for node CPU/RAM and function CPU/RAM.
- Include optional power queries for Scaphandre.
**Tests**
- Manual: verify file loads and placeholders render.

### Objective 2: Query runner
- Support range and instant queries.
- Retry until data appears or timeout (legacy behavior).
**Tests**
- Unit test: stub Prometheus response, verify avg value.
- Unit test: empty results trigger retry.

### Objective 3: Function metrics
- For each function, build queries with `{function_name}`.
- If Scaphandre enabled, allow `{pid_regex}`.
**Tests**
- Manual: query for a deployed function returns > 0 CPU.

### Objective 4: CSV output
- Emit per-config/iteration metrics with stable column names.
**Tests**
- Unit test: CSV headers include all functions.

## Acceptance criteria
- Metrics are collected for each config.
- Output columns consistent with legacy naming.

## Dependencies
- DFaaS-2 (generator consumes metrics)
- DFaaS-3 (Prometheus installed)

