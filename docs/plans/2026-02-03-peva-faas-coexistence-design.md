# PEVA-faas Coexistence Design

**Goal:** Support two distinct plugins, `dfaas` and `peva_faas`, running side-by-side with separate identities, config keys, outputs, metrics, and Grafana dashboards.

**Architecture:**
- Keep the existing `dfaas` plugin in-repo unchanged.
- Add the `peva_faas` plugin as a separate Git submodule at `lb_plugins/plugins/peva_faas`.
- Update the `peva_faas` internal ID, config, metrics, dashboards, paths, and tests to avoid collisions with `dfaas`.

**Components:**
- **Repo main:**
  - `lb_plugins/plugins/dfaas` (existing plugin).
  - `lb_plugins/plugins/peva_faas` (submodule).
  - Tests: `tests/unit/lb_plugins/dfaas/*` (existing) plus new `tests/unit/lb_plugins/peva_faas/*`.
- **Submodule `PEVA-faas`:**
  - Code derived from `dfaas`, renamed internally to `peva_faas`.
  - Distinct config key: `plugins.peva_faas`.
  - Distinct output/workspace paths.
  - Distinct labels and renamed metric series.
  - Distinct Grafana UIDs and dashboards.

**Data flow:**
- Discovery scans `lb_plugins/plugins/*/plugin.py` and registers both plugins via distinct `NAME` values.
- Config parsing uses `plugins.dfaas` and `plugins.peva_faas` independently.
- Outputs and logs are written to separate directories; metrics emit distinct label values and metric names.

**Error handling:**
- Keep existing error behavior; ensure error messages mention `peva_faas` when applicable.
- Validate config sections for `peva_faas` explicitly (similar to `dfaas`).

**Testing:**
- Keep current `dfaas` tests unchanged.
- Add mirrored `peva_faas` tests to validate:
  - config key parsing (`plugins.peva_faas`)
  - playbook paths
  - queries + metrics names
  - dashboard UID updates
  - output path separation

**Migration/rollout:**
- No breaking changes for users of `dfaas`.
- New users can opt into `peva_faas` by selecting workload `peva_faas` and defining `plugins.peva_faas` in config.

