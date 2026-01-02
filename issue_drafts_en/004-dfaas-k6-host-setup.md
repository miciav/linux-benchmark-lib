# DFaaS-4: k6 host setup + run playbook (workspace per target)

## Context
k6 runs on a dedicated host. Each target host must map to a dedicated workspace under a common root. The runner will invoke playbooks to run k6.

## Goal
- Install k6 from the official repo on the k6-host.
- Create a workspace root and per-target subdirs.
- Provide a playbook to run k6 with `--summary-export`.

## Partial objectives + tests
### Objective 1: Install k6
- Add official k6 repo and install package.
**Tests**
- `k6 version` returns successfully.

### Objective 2: Workspace layout
- Create `/var/lib/dfaas-k6/<target>/` and subdirs for run/config.
**Tests**
- Directory exists and is writable by Ansible user.

### Objective 3: Run playbook
- Accept vars: `target_name`, `run_id`, `config_id`, `script_src`, `summary_dest`.
- Copy script into workspace and run k6.
**Tests**
- Run against `httpbin` (no OpenFaaS required), verify `summary.json` created.

### Objective 4: Logs and artifacts
- Save stdout/stderr to `k6.log` under config dir.
**Tests**
- `k6.log` exists and contains run summary.

## Acceptance criteria
- k6 installed and runs via Ansible playbook.
- Summary exported for each config run.
- Workspace separation by target.

## Dependencies
- DFaaS-2 uses the run playbook.

