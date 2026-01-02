# DFaaS-3: Target host setup (k3s + OpenFaaS + Prometheus + exporters)

## Context
Each target host must run k3s, OpenFaaS, and a minimal observability stack (Prometheus + node-exporter + cAdvisor). Setup must be Ansible-driven and idempotent.

## Goal
Provide Ansible playbooks to install and configure k3s/OpenFaaS/Prometheus on the target host, and deploy OpenFaaS store functions.

## Scope
- k3s installation
- OpenFaaS installation
- Prometheus + exporters
- OpenFaaS functions deployment

## Partial objectives + tests
### Objective 1: k3s install
- Install k3s (official script), ensure kubeconfig available for Ansible user.
**Tests**
- Command: `k3s kubectl get nodes` returns Ready node.

### Objective 2: OpenFaaS install
- Install OpenFaaS via helm/arkade.
- Expose gateway on NodePort 31112.
- Configure `faas-cli` auth.
**Tests**
- `kubectl -n openfaas rollout status deploy/gateway`
- `faas-cli list` succeeds on target.

### Objective 3: Prometheus + exporters (minimal)
- Apply manifests for node-exporter, cAdvisor, Prometheus.
- Expose Prometheus on 9090 NodePort.
**Tests**
- `curl http://<target>:9090/-/ready` returns 200.
- Query CPU usage returns data.

### Objective 4: Deploy OpenFaaS functions
- Deploy store functions listed in config.
**Tests**
- `faas-cli list` includes the functions.
- `curl http://<target>:31112/function/<name>` returns 200.

### Objective 5 (optional): Scaphandre
- Install and configure Scaphandre if enabled.
**Tests**
- Prometheus query `scaph_host_power_microwatts` returns data.

## Acceptance criteria
- Playbooks are idempotent.
- Target host is fully usable for DFaaS generator runs.

## Dependencies
- DFaaS-1 (functions list in config)

