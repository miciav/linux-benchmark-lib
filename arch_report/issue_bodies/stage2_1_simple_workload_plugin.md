## Description
Introduce a `SimpleWorkloadPlugin` base to remove duplication in plugin metadata and asset getters.

## Plan
1. Add a base class with class attributes for `name`, `description`, and asset paths.
2. Update plugins with identical metadata surfaces to inherit it.
3. Keep the `WorkloadPlugin` contract intact and update unit tests.

## Acceptance Criteria
- High-similarity plugins share a common base.
- Plugin registry and CLI listing work as before.

## Risk
High. Behavior drift possible.

## Evidence
- `arch_report/duplication_candidates_lb_plugins.txt`
- `lb_plugins/plugins/stress_ng/plugin.py:90`
- `lb_plugins/plugins/dd/plugin.py:168`
