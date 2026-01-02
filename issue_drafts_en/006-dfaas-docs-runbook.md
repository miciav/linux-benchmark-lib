# DFaaS-6: Documentation + runbook

## Context
We need operator documentation for the DFaaS plugin: architecture, setup, config, run flow, and troubleshooting.

## Goal
Provide a complete runbook for target host + k6-host setup and DFaaS runs.

## Partial objectives + tests
### Objective 1: Architecture section
- Explain target host vs k6-host and communication paths.
**Tests**
- Manual review: diagram + port list present.

### Objective 2: Setup steps
- Document playbook usage for target and k6-host.
- Include prerequisites and required ports.
**Tests**
- Manual: follow steps on a fresh VM and confirm commands succeed.

### Objective 3: Configuration example
- Full YAML config example with comments.
**Tests**
- Manual: run config validation and ensure no errors.

### Objective 4: Run flow + outputs
- Describe single-config loop, cooldown, dominant skip.
- Document output files and locations.
**Tests**
- Manual: run a short benchmark and verify outputs match doc.

### Objective 5: Troubleshooting
- Common errors and fixes: gateway down, Prometheus unreachable, k6 SSH.
**Tests**
- Manual: intentionally break one dependency and follow steps to recover.

## Acceptance criteria
- Doc includes architecture, setup, config, run flow, troubleshooting.
- Steps are reproducible.

## Dependencies
- DFaaS-1..5 (needs final behavior defined).

