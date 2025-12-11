Test suite layout and markers
==============================

Folders
-------
- `unit/` – fast tests. Domain-specific cases live under `unit/lb_*`; cross-cutting/unit helpers now live in `unit/common/`.
- `integration/` – medium-speed service-level checks that do not provision Docker or Multipass.
- `e2e/` – slow paths that provision Multipass VMs, build Docker images, or run real workloads end to end.
- `helpers/` – shared test utilities (e.g., Multipass helpers).
- `fixtures/` – static data and golden outputs; prefer adding new fixtures here instead of under test modules.

Markers
-------
- `unit` – fast, no external services.
- `integration` – service-level, no provisioning.
- `e2e` – end-to-end, may provision VMs/containers.
- `docker`, `multipass`, `slow`, `slowest` – feature/velocity flags to combine with the above.

Running subsets
---------------
- Fast only: `uv run pytest -m "unit"`
- Exclude heavy flows: `uv run pytest -m "not e2e and not multipass and not docker"`
