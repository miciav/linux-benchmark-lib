# DFAAS-FIX-2: Complete README documentation

## Context
The DFaaS plugin README is incomplete, missing critical sections that users and developers need to understand and use the plugin effectively.

## Goal
Complete the README with all required documentation sections to match project standards.

## Scope
- Add missing documentation sections
- Ensure consistency with other plugin READMEs
- Include practical examples

## Non-scope
- API documentation (covered by docstrings)
- Tutorial-style guides

## Current State
The README (`lb_plugins/plugins/dfaas/README.md`) currently has:
- Basic description
- High-level feature list
- Configuration example

**Missing sections**:
- Architecture overview
- Prerequisites
- Setup steps
- Run flow description
- Outputs specification
- Troubleshooting guide

## Required Sections

### 1. Architecture
Describe the component interactions:
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Target    │     │  k6 Host    │     │  Controller │
│  (k3s/OF)   │◄────│  (load gen) │◄────│  (Ansible)  │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       └───────────────────┴───────────────────┘
                     Prometheus
```

### 2. Prerequisites
- k3s cluster on target host
- SSH access to k6 host
- Python 3.12+
- ansible-playbook, faas-cli installed locally
- Network connectivity between hosts

### 3. Setup Steps
1. Configure target host (k3s + OpenFaaS + Prometheus)
2. Configure k6 host (k6 binary + workspace)
3. Create benchmark configuration
4. Run setup playbooks

### 4. Run Flow
1. Generator enumerates function/rate configurations
2. For each config:
   - Wait for cooldown (CPU/RAM below threshold)
   - Generate k6 script
   - Execute via Ansible on k6 host
   - Collect Prometheus metrics
   - Check overload conditions
   - Write results to CSV

### 5. Outputs
| File | Description |
|------|-------------|
| `results.csv` | Per-configuration metrics (success rate, latency, CPU, RAM) |
| `skipped.csv` | Configurations skipped due to dominance/existing index |
| `index.csv` | Index of completed configurations |
| `summaries/` | Raw k6 summary JSON files |
| `scripts/` | Generated k6 scripts |

### 6. Troubleshooting
Common issues and solutions:
- Prometheus not reachable
- k6 SSH connection fails
- OpenFaaS functions not ready
- Cooldown timeout exceeded

## Partial Objectives + Tests

### Objective 1: Add Architecture section
Document component diagram and data flow.
**Tests**: Manual review

### Objective 2: Add Prerequisites section
List all requirements with version constraints.
**Tests**: `test_dfaas_readme_has_required_sections` passes

### Objective 3: Add Setup Steps section
Step-by-step setup guide with commands.
**Tests**: Manual walkthrough verification

### Objective 4: Add Run Flow section
Describe execution sequence with diagram.
**Tests**: Manual review

### Objective 5: Add Outputs section
Document all output files with schemas.
**Tests**: Manual review

### Objective 6: Add Troubleshooting section
Common issues with solutions.
**Tests**: Manual review

## Acceptance Criteria
- [ ] README contains all 6 required sections
- [ ] `test_dfaas_readme_has_required_sections` passes
- [ ] Examples are copy-paste ready
- [ ] Consistent formatting with other plugin READMEs

## Files to Modify
- `lb_plugins/plugins/dfaas/README.md`

## Dependencies
- 011 (test fix) should be done first to align expectations

## Effort
~2 hours

