## Description
Unify command-based generators using a `CommandSpec` + `ResultParser` strategy to remove duplication.

## Plan
1. Define a template method in `CommandGenerator` with `CommandSpec` and `ResultParser` hooks.
2. Implement strategies for `StressNG`, `DD`, `Sysbench`, `UnixBench`, `Yabs`, and `Geekbench`.
3. Add unit tests for command parsing and post-run handling.

## Acceptance Criteria
- Command generators share a common template.
- Tests validate parsing and post-run behavior.

## Risk
High. Multiple plugins affected.

## Evidence
- `arch_report/duplication_candidates_lb_plugins.txt`
- `lb_plugins/plugins/stress_ng/plugin.py:32`
- `lb_plugins/plugins/dd/plugin.py:34`
