# DFaaS Epic: k6 + k3s/OpenFaaS + Prometheus workload plugin

## Objective
Deliver a DFaaS workload plugin for linux-benchmark-lib that reproduces the legacy sampling workflow using k6 on a dedicated host, and collects Prometheus metrics from a k3s/OpenFaaS target.

## Scope
- Config schema & legacy rules (cooldown/overload/dominance)
- Generator orchestration (single-config loop)
- Ansible setup for target host (k3s/OpenFaaS/Prometheus)
- Ansible setup for k6-host (k6 + run playbook)
- Prometheus query set (queries.yml)
- Runbook documentation

## Out of scope
- Core library changes
- Multi-cluster orchestration beyond target/k6 mapping

## Milestones
1) Config schema + rules defined (DFaaS-1)
2) k6 host runnable (DFaaS-4)
3) Target host stack ready (DFaaS-3)
4) Generator end-to-end (DFaaS-2)
5) Metrics collection (DFaaS-5)
6) Docs (DFaaS-6)

## Linked issues
- #52 DFaaS-1: config schema + legacy rules
- #53 DFaaS-2: generator orchestration
- #54 DFaaS-3: target setup (k3s/OpenFaaS/Prometheus)
- #55 DFaaS-4: k6 host setup
- #56 DFaaS-5: Prometheus queries
- #57 DFaaS-6: documentation/runbook

## Acceptance criteria
- All linked issues closed with their test gates met.
- End-to-end flow validated on at least 1 target host and 1 k6 host.

