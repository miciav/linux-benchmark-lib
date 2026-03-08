# Mypy Debt Inventory

Date: 2026-03-08

## Command Baseline

- `core`: `bash scripts/mypy_core.sh --hide-error-context --no-color-output --no-error-summary`
- `plugins`: `bash scripts/mypy_plugins.sh --hide-error-context --no-color-output --no-error-summary`
- `all`: `bash scripts/mypy_all.sh --hide-error-context --no-color-output --no-error-summary`

## Current Counts

Note: the `core` profile now uses `--follow-imports=silent` rather than `skip`.
`skip` turned `@model_validator` into false `untyped-decorator` debt because it
prevented the `pydantic.mypy` plugin from analyzing imports.

- `core`: `210` errors
  - `lb_runner`: `31`
  - `lb_app`: `60`
  - `lb_controller`: `35`
  - `lb_ui`: `84`
- `plugins`: `107` errors
  - `lb_plugins`: `79`
  - `lb_runner`: `20`
  - `lb_common`: `7`
  - `lb_provisioner`: `1`
- `all`: `295` errors
  - `lb_gui`: `35`
  - `lb_runner`: `26`
  - `lb_plugins`: `79`
  - `lb_common`: `7`
  - `lb_provisioner`: `1`
  - `lb_analytics`: `4`
  - `lb_app`: `58`
  - `lb_controller`: `34`
  - `lb_ui`: `51`

## Dominant Error Categories (`core`)

- `no-untyped-def`: `54`
- `untyped-decorator`: `48`
- `no-any-return`: `25`
- `arg-type`: `16`
- `assignment`: `12`
- `unused-ignore`: `9`
- `call-arg`: `8`
- `unreachable`: `7`

## High-Value Batches

### Batch A: Signal Handling And Stop Flow

**Why first:** concentrated core logic, low file count, high leverage on `lb_runner` and `lb_controller`.

**Files:**
- [lb_runner/engine/stop_token.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_runner/engine/stop_token.py)
- [lb_controller/engine/interrupts.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_controller/engine/interrupts.py)
- [lb_controller/adapters/ansible_helpers.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_controller/adapters/ansible_helpers.py)

**Typical errors:**
- `assignment`
- `no-untyped-def`
- `comparison-overlap`
- `unused-ignore`
- `union-attr`

**Difficulty:** `M`

### Batch B: App Output And Execution Helpers

**Why second:** large concentration inside `lb_app`, mostly annotation and `Any` cleanup rather than architecture.

**Files:**
- [lb_app/services/run_output.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_app/services/run_output.py)
- [lb_app/services/run_output_parsing.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_app/services/run_output_parsing.py)
- [lb_app/services/run_execution.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_app/services/run_execution.py)
- [lb_app/services/run_plan.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_app/services/run_plan.py)
- [lb_app/client.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_app/client.py)

**Typical errors:**
- `no-untyped-def`
- `no-any-return`
- `call-arg`
- `attr-defined`
- `list-item`

**Difficulty:** `M`

### Batch C: UI Command And TUI Typing

**Why third:** biggest area by count, but many errors are repetitive and can be reduced systematically once one pattern is fixed.

**Files:**
- [lb_ui/cli/commands](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_ui/cli/commands)
- [lb_ui/tui/screens/picker_screen.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_ui/tui/screens/picker_screen.py)
- [lb_ui/tui/core/capabilities.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_ui/tui/core/capabilities.py)
- [lb_ui/tui/adapters/tui_adapter.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_ui/tui/adapters/tui_adapter.py)

**Typical errors:**
- `untyped-decorator`
- `no-untyped-def`
- `no-any-return`
- `arg-type`

**Difficulty:** `M/L`

### Batch D: Journal And Controller State Models

**Why fourth:** several controller errors are tied to recent work and likely quick wins.

**Files:**
- [lb_controller/services/journal.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_controller/services/journal.py)
- [lb_controller/services/journal_sync.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_controller/services/journal_sync.py)
- [lb_controller/services/run_catalog_service.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_controller/services/run_catalog_service.py)
- [lb_controller/adapters/ansible_runner.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_controller/adapters/ansible_runner.py)
- [lb_controller/adapters/playbooks.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_controller/adapters/playbooks.py)

**Typical errors:**
- `arg-type`
- `no-any-return`
- `valid-type`
- `no-untyped-def`

**Difficulty:** `M`

### Batch E: Runner Collectors And Config Models

**Why fifth:** this area is smaller than UI but contains shared types used broadly.

**Files:**
- [lb_runner/models/config.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_runner/models/config.py)
- [lb_runner/metric_collectors/_base_collector.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_runner/metric_collectors/_base_collector.py)
- [lb_runner/metric_collectors/builtin.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_runner/metric_collectors/builtin.py)
- [lb_runner/metric_collectors/cli_collector.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_runner/metric_collectors/cli_collector.py)
- [lb_runner/metric_collectors/psutil_collector.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_runner/metric_collectors/psutil_collector.py)

**Typical errors:**
- `untyped-decorator`
- `no-any-return`
- `valid-type`
- `assignment`
- `union-attr`

**Difficulty:** `M`

### Batch F: Plugin Contract Cleanup

**Why later:** highest plugin count, but spread across many workload modules; best handled after core gate is healthy.

**Files:**
- [lb_plugins/interface.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_plugins/interface.py)
- [lb_plugins/installer.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_plugins/installer.py)
- [lb_plugins/user_plugins.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_plugins/user_plugins.py)
- [lb_plugins/plugins](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_plugins/plugins)

**Typical errors:**
- `override`
- `union-attr`
- `no-any-return`
- `call-overload`

**Difficulty:** `L`

### Batch G: GUI And Analytics

**Why last:** not part of the core gate, but visible in `mypy-all`.

**Files:**
- [lb_gui/resources/__init__.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_gui/resources/__init__.py)
- [lb_gui/widgets](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_gui/widgets)
- [lb_analytics/engine/aggregators/collectors.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_analytics/engine/aggregators/collectors.py)
- [lb_analytics/engine/aggregators/data_handler.py](/Users/micheleciavotta/Downloads/linux-benchmark-lib/lb_analytics/engine/aggregators/data_handler.py)

**Difficulty:** `S/M`

## Recommended Execution Order

1. Batch A
2. Batch D
3. Batch B
4. Batch E
5. Batch C
6. Batch F
7. Batch G

## Notes

- `core` is now a reliable gate: no vendored Ansible collection files and no transitive leaks into unrelated top-level packages.
- `plugins` and `all` are now mostly first-party debt; remaining failures are no longer dominated by missing stubs or vendored code.
- The next implementation pass should target one batch at a time with fresh `pytest` + `mypy` verification after each batch.
