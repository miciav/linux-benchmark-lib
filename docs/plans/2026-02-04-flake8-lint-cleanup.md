# Flake8 Lint Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `uv run flake8 .` pass by fixing remaining lint categories (E501, W29x/E30x/E111/E117/W391, I250, CCR001) across the repo.

**Architecture:** Use category-aware, module-scoped cleanup passes. For whitespace/formatting issues, apply minimal edits that do not change behavior. For CCR001, refactor into small helpers while preserving semantics. Use `flake8 --select` as the verification loop.

**Tech Stack:** Python 3.13, flake8, flake8-tidy-imports, flake8-cognitive-complexity.

**Notes:**
- **TDD exception approved** for this lint-only cleanup. Use flake8 checks as the verification step.
- Keep behavioral changes out of scope; CCR001 fixes must be pure refactors.

### Task 1: Baseline Capture (Targeted Lint Set)

**Files:**
- Modify: none

**Step 1: Capture current violations**

Run: `uv run flake8 . --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL with current list of violations.

**Step 2: Save baseline snapshot**

Run: `uv run flake8 . --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250 > /tmp/flake8.txt || true`
Expected: `/tmp/flake8.txt` populated.

### Task 2: Example + lb_analytics Cleanup

**Files:**
- Modify: `example.py`
- Modify: `lb_analytics/api.py`
- Modify: `lb_analytics/engine/aggregators/collectors.py`
- Modify: `lb_analytics/engine/aggregators/data_handler.py`
- Modify: `lb_analytics/engine/service.py`
- Modify: `lb_analytics/reporting/generator.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 example.py lb_analytics --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix whitespace/indentation/blank line issues**

Edit the listed files to resolve W29x/E30x/E111/E117/W391. Keep changes minimal.

**Step 3: Fix E501**

Reflow lines to <= 88 chars (prefer wrapping over changing strings/behavior).

**Step 4: Fix CCR001**

Refactor complex functions into helpers; no behavior changes.

**Step 5: Re-run targeted lint**

Run: `uv run flake8 example.py lb_analytics --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS (no output).

**Step 6: Commit**

Run:
```bash
git add example.py lb_analytics
git commit -m "Fix flake8 issues in analytics and example"
```

### Task 3: lb_app Cleanup

**Files:**
- Modify: `lb_app/client.py`
- Modify: `lb_app/services/config_defaults.py`
- Modify: `lb_app/services/config_repository.py`
- Modify: `lb_app/services/config_service.py`
- Modify: `lb_app/services/doctor_service.py`
- Modify: `lb_app/services/doctor_types.py`
- Modify: `lb_app/services/execution_loop.py`
- Modify: `lb_app/services/provision_service.py`
- Modify: `lb_app/services/remote_run_coordinator.py`
- Modify: `lb_app/services/run_context_builder.py`
- Modify: `lb_app/services/run_events.py`
- Modify: `lb_app/services/run_execution.py`
- Modify: `lb_app/services/run_journal.py`
- Modify: `lb_app/services/run_logging.py`
- Modify: `lb_app/services/run_output.py`
- Modify: `lb_app/services/run_output_formatting.py`
- Modify: `lb_app/services/run_output_parsing.py`
- Modify: `lb_app/services/run_pipeline.py`
- Modify: `lb_app/services/run_plan.py`
- Modify: `lb_app/services/run_service.py`
- Modify: `lb_app/services/run_system_info.py`
- Modify: `lb_app/services/session_manager.py`
- Modify: `lb_app/services/test_service.py`
- Modify: `lb_app/ui_interfaces.py`
- Modify: `lb_app/viewmodels/dashboard.py`
- Modify: `lb_app/viewmodels/run_viewmodels.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 lb_app --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix whitespace/indentation/blank line issues**

Resolve W29x/E30x/E111/E117/W391 across the listed files.

**Step 3: Fix E501**

Reflow long lines; keep strings/logging/messages intact when possible.

**Step 4: Fix CCR001**

Refactor complex functions into helpers; no behavior change.

**Step 5: Re-run targeted lint**

Run: `uv run flake8 lb_app --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 6: Commit**

Run:
```bash
git add lb_app
git commit -m "Fix flake8 issues in lb_app"
```

### Task 4: lb_common Cleanup

**Files:**
- Modify: `lb_common/logs/core.py`
- Modify: `lb_common/logs/handlers/jsonl_handler.py`
- Modify: `lb_common/logs/handlers/loki_handler.py`
- Modify: `lb_common/logs/handlers/loki_helpers.py`
- Modify: `lb_common/observability/grafana_client.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 lb_common --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix formatting and complexity**

Resolve W29x/E30x/E111/E117/W391 and E501. Refactor CCR001 functions with helpers.

**Step 3: Re-run targeted lint**

Run: `uv run flake8 lb_common --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 4: Commit**

Run:
```bash
git add lb_common
git commit -m "Fix flake8 issues in lb_common"
```

### Task 5: lb_controller Cleanup

**Files:**
- Modify: `lb_controller/adapters/ansible_helpers.py`
- Modify: `lb_controller/adapters/ansible_runner.py`
- Modify: `lb_controller/adapters/playbooks.py`
- Modify: `lb_controller/adapters/remote_runner.py`
- Modify: `lb_controller/ansible/callback_plugins/lb_events.py`
- Modify: `lb_controller/engine/lifecycle.py`
- Modify: `lb_controller/engine/run_state_builders.py`
- Modify: `lb_controller/engine/session.py`
- Modify: `lb_controller/engine/stop_logic.py`
- Modify: `lb_controller/engine/stops.py`
- Modify: `lb_controller/models/pending.py`
- Modify: `lb_controller/services/connectivity_service.py`
- Modify: `lb_controller/services/journal.py`
- Modify: `lb_controller/services/journal_sync.py`
- Modify: `lb_controller/services/run_catalog_service.py`
- Modify: `lb_controller/services/run_orchestrator.py`
- Modify: `lb_controller/services/workload_runner.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 lb_controller --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix formatting and complexity**

Resolve whitespace/indentation issues and E501. Refactor CCR001 functions via helpers.

**Step 3: Re-run targeted lint**

Run: `uv run flake8 lb_controller --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 4: Commit**

Run:
```bash
git add lb_controller
git commit -m "Fix flake8 issues in lb_controller"
```

### Task 6: lb_gui Cleanup

**Files:**
- Modify: `lb_gui/services/config_service.py`
- Modify: `lb_gui/services/doctor_service.py`
- Modify: `lb_gui/viewmodels/analytics_vm.py`
- Modify: `lb_gui/viewmodels/doctor_vm.py`
- Modify: `lb_gui/viewmodels/results_vm.py`
- Modify: `lb_gui/viewmodels/run_setup_vm.py`
- Modify: `lb_gui/views/doctor_view.py`
- Modify: `lb_gui/views/plugins_view.py`
- Modify: `lb_gui/views/run_setup_view.py`
- Modify: `lb_gui/windows/main_window.py`
- Modify: `lb_gui/workers/run_worker.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 lb_gui --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix formatting and complexity**

Resolve whitespace/indentation issues and E501. Refactor CCR001 functions.

**Step 3: Re-run targeted lint**

Run: `uv run flake8 lb_gui --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 4: Commit**

Run:
```bash
git add lb_gui
git commit -m "Fix flake8 issues in lb_gui"
```

### Task 7: lb_plugins Cleanup

**Files:**
- Modify: `lb_plugins/__init__.py`
- Modify: `lb_plugins/api.py`
- Modify: `lb_plugins/base_generator.py`
- Modify: `lb_plugins/builtin.py`
- Modify: `lb_plugins/discovery.py`
- Modify: `lb_plugins/interface.py`
- Modify: `lb_plugins/observability.py`
- Modify: `lb_plugins/plugins/_user/dummy_plugin/dummy.py`
- Modify: `lb_plugins/plugins/_user/remote/dummy.py`
- Modify: `lb_plugins/plugins/baseline/plugin.py`
- Modify: `lb_plugins/plugins/dd/plugin.py`
- Modify: `lb_plugins/plugins/dfaas/config.py`
- Modify: `lb_plugins/plugins/dfaas/generator.py`
- Modify: `lb_plugins/plugins/dfaas/plugin.py`
- Modify: `lb_plugins/plugins/dfaas/queries.py`
- Modify: `lb_plugins/plugins/dfaas/services/__init__.py`
- Modify: `lb_plugins/plugins/dfaas/services/annotation_service.py`
- Modify: `lb_plugins/plugins/dfaas/services/k6_runner.py`
- Modify: `lb_plugins/plugins/dfaas/services/plan_builder.py`
- Modify: `lb_plugins/plugins/dfaas/services/result_builder.py`
- Modify: `lb_plugins/plugins/dfaas/services/run_execution.py`
- Modify: `lb_plugins/plugins/fio/plugin.py`
- Modify: `lb_plugins/plugins/geekbench/plugin.py`
- Modify: `lb_plugins/plugins/hpl/plugin.py`
- Modify: `lb_plugins/plugins/peva_faas/config.py`
- Modify: `lb_plugins/plugins/peva_faas/generator.py`
- Modify: `lb_plugins/plugins/peva_faas/plugin.py`
- Modify: `lb_plugins/plugins/peva_faas/queries.py`
- Modify: `lb_plugins/plugins/peva_faas/services/__init__.py`
- Modify: `lb_plugins/plugins/peva_faas/services/annotation_service.py`
- Modify: `lb_plugins/plugins/peva_faas/services/k6_runner.py`
- Modify: `lb_plugins/plugins/peva_faas/services/plan_builder.py`
- Modify: `lb_plugins/plugins/peva_faas/services/result_builder.py`
- Modify: `lb_plugins/plugins/peva_faas/services/run_execution.py`
- Modify: `lb_plugins/plugins/phoronix_test_suite/__init__.py`
- Modify: `lb_plugins/plugins/phoronix_test_suite/plugin.py`
- Modify: `lb_plugins/plugins/stream/__init__.py`
- Modify: `lb_plugins/plugins/stream/plugin.py`
- Modify: `lb_plugins/plugins/stress_ng/plugin.py`
- Modify: `lb_plugins/plugins/sysbench/plugin.py`
- Modify: `lb_plugins/plugins/unixbench/plugin.py`
- Modify: `lb_plugins/plugins/yabs/plugin.py`
- Modify: `lb_plugins/registry.py`
- Modify: `lb_plugins/settings.py`
- Modify: `lb_plugins/table.py`
- Modify: `lb_plugins/user_plugins.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 lb_plugins --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix formatting and complexity**

Resolve whitespace/indentation issues, E501, and CCR001 (refactor only).

**Step 3: Re-run targeted lint**

Run: `uv run flake8 lb_plugins --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 4: Commit**

Run:
```bash
git add lb_plugins
git commit -m "Fix flake8 issues in lb_plugins"
```

### Task 8: lb_provisioner Cleanup

**Files:**
- Modify: `lb_provisioner/engine/service.py`
- Modify: `lb_provisioner/providers/docker.py`
- Modify: `lb_provisioner/providers/multipass.py`
- Modify: `lb_provisioner/providers/remote.py`
- Modify: `lb_provisioner/services/loki_grafana.py`
- Modify: `lb_provisioner/services/utils.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 lb_provisioner --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix formatting and complexity**

Resolve whitespace/indentation issues, E501, and CCR001.

**Step 3: Re-run targeted lint**

Run: `uv run flake8 lb_provisioner --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 4: Commit**

Run:
```bash
git add lb_provisioner
git commit -m "Fix flake8 issues in lb_provisioner"
```

### Task 9: lb_runner Cleanup

**Files:**
- Modify: `lb_runner/engine/context.py`
- Modify: `lb_runner/engine/execution.py`
- Modify: `lb_runner/engine/executor.py`
- Modify: `lb_runner/engine/planning.py`
- Modify: `lb_runner/engine/runner.py`
- Modify: `lb_runner/engine/stop_token.py`
- Modify: `lb_runner/metric_collectors/_base_collector.py`
- Modify: `lb_runner/metric_collectors/aggregators.py`
- Modify: `lb_runner/metric_collectors/cli_collector.py`
- Modify: `lb_runner/metric_collectors/psutil_collector.py`
- Modify: `lb_runner/models/config.py`
- Modify: `lb_runner/models/loki_env.py`
- Modify: `lb_runner/registry.py`
- Modify: `lb_runner/services/async_localrunner.py`
- Modify: `lb_runner/services/collector_coordinator.py`
- Modify: `lb_runner/services/results.py`
- Modify: `lb_runner/services/runner_output_manager.py`
- Modify: `lb_runner/services/storage.py`
- Modify: `lb_runner/services/system_info.py`
- Modify: `lb_runner/services/system_info_cli.py`
- Modify: `lb_runner/services/system_info_collectors.py`
- Modify: `lb_runner/services/system_info_io.py`
- Modify: `lb_runner/services/system_info_types.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 lb_runner --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix formatting and complexity**

Resolve whitespace/indentation issues, E501, and CCR001.

**Step 3: Re-run targeted lint**

Run: `uv run flake8 lb_runner --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 4: Commit**

Run:
```bash
git add lb_runner
git commit -m "Fix flake8 issues in lb_runner"
```

### Task 10: lb_ui Cleanup

**Files:**
- Modify: `lb_ui/cli/__init__.py`
- Modify: `lb_ui/cli/commands/config.py`
- Modify: `lb_ui/cli/commands/doctor.py`
- Modify: `lb_ui/cli/commands/plugin.py`
- Modify: `lb_ui/cli/commands/provision.py`
- Modify: `lb_ui/cli/commands/resume.py`
- Modify: `lb_ui/cli/commands/run.py`
- Modify: `lb_ui/cli/commands/runs.py`
- Modify: `lb_ui/cli/commands/test.py`
- Modify: `lb_ui/cli/main.py`
- Modify: `lb_ui/flows/config_wizard.py`
- Modify: `lb_ui/flows/selection.py`
- Modify: `lb_ui/notifications/base.py`
- Modify: `lb_ui/notifications/manager.py`
- Modify: `lb_ui/notifications/providers/desktop.py`
- Modify: `lb_ui/notifications/providers/webhook.py`
- Modify: `lb_ui/presenters/dashboard.py`
- Modify: `lb_ui/presenters/plan.py`
- Modify: `lb_ui/services/assets.py`
- Modify: `lb_ui/services/tray.py`
- Modify: `lb_ui/tui/adapters/dashboard_handle.py`
- Modify: `lb_ui/tui/adapters/tui_adapter.py`
- Modify: `lb_ui/tui/screens/picker_screen.py`
- Modify: `lb_ui/tui/system/components/dashboard_rollup.py`
- Modify: `lb_ui/tui/system/components/flat_picker_panel.py`
- Modify: `lb_ui/tui/system/components/form.py`
- Modify: `lb_ui/tui/system/components/progress.py`
- Modify: `lb_ui/tui/system/components/table.py`
- Modify: `lb_ui/tui/system/components/table_layout.py`
- Modify: `lb_ui/tui/system/facade.py`
- Modify: `lb_ui/tui/system/headless.py`
- Modify: `lb_ui/tui/system/models.py`
- Modify: `lb_ui/wiring/dependencies.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 lb_ui --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix formatting and complexity**

Resolve whitespace/indentation issues, E501, and CCR001.

**Step 3: Re-run targeted lint**

Run: `uv run flake8 lb_ui --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 4: Commit**

Run:
```bash
git add lb_ui
git commit -m "Fix flake8 issues in lb_ui"
```

### Task 11: scripts + molecule Cleanup

**Files:**
- Modify: `scripts/arch_smells.py`
- Modify: `scripts/bump_version/bump_version.py`
- Modify: `scripts/check_api_imports.py`
- Modify: `scripts/component_import_graph.py`
- Modify: `scripts/gen_release_notes.py`
- Modify: `scripts/graph_dependencies.py`
- Modify: `molecule/controller-stop/scripts/controller_stop_runner.py`
- Modify: `molecule/controller-stop/scripts/test_controller_stop.py`
- Modify: `molecule/controller-stop/tests/test_controller_stop.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 scripts molecule --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix formatting and complexity**

Resolve whitespace/indentation issues, E501, and CCR001.

**Step 3: Re-run targeted lint**

Run: `uv run flake8 scripts molecule --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 4: Commit**

Run:
```bash
git add scripts molecule
git commit -m "Fix flake8 issues in scripts and molecule"
```

### Task 12: tests Cleanup

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/e2e/test_benchmark_real.py`
- Modify: `tests/e2e/test_dfaas_multipass_e2e.py`
- Modify: `tests/e2e/test_multipass_baseline.py`
- Modify: `tests/e2e/test_multipass_benchmark.py`
- Modify: `tests/e2e/test_multipass_k6_install.py`
- Modify: `tests/e2e/test_multipass_multi_workloads.py`
- Modify: `tests/e2e/test_multipass_single_workloads.py`
- Modify: `tests/e2e/test_multipass_ssh.py`
- Modify: `tests/e2e/test_plugin_git_install_e2e.py`
- Modify: `tests/e2e/test_plugin_multipass_assets.py`
- Modify: `tests/gui/windows/test_main_window_workflow.py`
- Modify: `tests/helpers/multipass.py`
- Modify: `tests/integration/lb_plugins/test_dfaas_docker_integration.py`
- Modify: `tests/integration/test_ansible_loki_env.py`
- Modify: `tests/integration/test_async_localrunner_events.py`
- Modify: `tests/integration/test_event_stream_polling.py`
- Modify: `tests/integration/test_local_runner.py`
- Modify: `tests/integration/test_log_streaming_integration.py`
- Modify: `tests/integration/test_resume_provisioning_docker_slow.py`
- Modify: `tests/inter_char/test_config_snapshot.py`
- Modify: `tests/inter_char/test_run_service_char.py`
- Modify: `tests/unit/cross_cutting/test_component_installability.py`
- Modify: `tests/unit/lb_analytics/test_collectors.py`
- Modify: `tests/unit/lb_analytics/test_data_handler.py`
- Modify: `tests/unit/lb_analytics/test_data_handler_builtin.py`
- Modify: `tests/unit/lb_app/test_config_remote_hosts.py`
- Modify: `tests/unit/lb_app/test_remote_run_coordinator.py`
- Modify: `tests/unit/lb_app/test_run_context_builder.py`
- Modify: `tests/unit/lb_app/test_run_service_session.py`
- Modify: `tests/unit/lb_common/test_env_utils.py`
- Modify: `tests/unit/lb_common/test_events.py`
- Modify: `tests/unit/lb_common/test_log_schema.py`
- Modify: `tests/unit/lb_common/test_loki_handler.py`
- Modify: `tests/unit/lb_controller/ansible_tests/test_ansible_executor_signals.py`
- Modify: `tests/unit/lb_controller/ansible_tests/test_ansible_output_formatter.py`
- Modify: `tests/unit/lb_controller/ansible_tests/test_lb_events_callback.py`
- Modify: `tests/unit/lb_controller/ansible_tests/test_setup_playbook_sync.py`
- Modify: `tests/unit/lb_controller/services_tests/test_journal.py`
- Modify: `tests/unit/lb_controller/test_collect_on_stop.py`
- Modify: `tests/unit/lb_controller/test_collect_playbook.py`
- Modify: `tests/unit/lb_controller/test_controller.py`
- Modify: `tests/unit/lb_controller/test_controller_runner.py`
- Modify: `tests/unit/lb_controller/test_controller_stop.py`
- Modify: `tests/unit/lb_controller/test_lb_event_parsing.py`
- Modify: `tests/unit/lb_controller/test_logging_adapter.py`
- Modify: `tests/unit/lb_controller/test_paths.py`
- Modify: `tests/unit/lb_controller/test_run_service_threaded.py`
- Modify: `tests/unit/lb_controller/test_run_state_builders.py`
- Modify: `tests/unit/lb_controller/test_services.py`
- Modify: `tests/unit/lb_controller/test_session.py`
- Modify: `tests/unit/lb_controller/test_stop_coordinator.py`
- Modify: `tests/unit/lb_gui/test_config_plugins_doctor_vm.py`
- Modify: `tests/unit/lb_gui/test_dashboard_vm.py`
- Modify: `tests/unit/lb_gui/test_run_setup_vm.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_config.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_cooldown.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_generator.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_grafana_setup.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_k6_runner_fabric.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_metrics_collector.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_playbooks.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_queries.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_result_builder.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_url_resolution.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_config.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_cooldown.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_docs.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_grafana_setup.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_metrics_collector.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_queries.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_result_builder.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_url_resolution.py`
- Modify: `tests/unit/lb_plugins/plugins/test_fio_plugin.py`
- Modify: `tests/unit/lb_plugins/plugins/test_fio_plugin_export.py`
- Modify: `tests/unit/lb_plugins/plugins/test_geekbench_plugin.py`
- Modify: `tests/unit/lb_plugins/plugins/test_stress_ng_plugin.py`
- Modify: `tests/unit/lb_plugins/plugins/test_sysbench_plugin.py`
- Modify: `tests/unit/lb_plugins/plugins/test_unixbench_plugin.py`
- Modify: `tests/unit/lb_plugins/plugins/test_yabs_plugin.py`
- Modify: `tests/unit/lb_plugins/test_plugin_export_csv.py`
- Modify: `tests/unit/lb_plugins/test_plugin_installer.py`
- Modify: `tests/unit/lb_plugins/test_plugin_registry.py`
- Modify: `tests/unit/lb_provisioner/test_grafana_client.py`
- Modify: `tests/unit/lb_provisioner/test_loki_grafana.py`
- Modify: `tests/unit/lb_provisioner/test_multipass_lifecycle.py`
- Modify: `tests/unit/lb_runner/engine_tests/test_base_collector.py`
- Modify: `tests/unit/lb_runner/engine_tests/test_executor.py`
- Modify: `tests/unit/lb_runner/models/test_benchmark_config.py`
- Modify: `tests/unit/lb_runner/plugins/test_baseline_plugin.py`
- Modify: `tests/unit/lb_runner/plugins/test_external_user_plugins_yaml.py`
- Modify: `tests/unit/lb_runner/plugins/test_pts_gmpbench.py`
- Modify: `tests/unit/lb_runner/plugins/test_pts_ramspeed.py`
- Modify: `tests/unit/lb_runner/plugins/test_stream.py`
- Modify: `tests/unit/lb_runner/services_tests/test_collect_metrics.py`
- Modify: `tests/unit/lb_runner/services_tests/test_system_info.py`
- Modify: `tests/unit/lb_runner/test_cli_collector.py`
- Modify: `tests/unit/lb_runner/test_local_runner_characterization.py`
- Modify: `tests/unit/lb_runner/test_local_runner_failures.py`
- Modify: `tests/unit/lb_runner/test_local_runner_unit.py`
- Modify: `tests/unit/lb_runner/test_loki_config_env.py`
- Modify: `tests/unit/lb_runner/test_output_helpers.py`
- Modify: `tests/unit/lb_runner/test_plugin_exports.py`
- Modify: `tests/unit/lb_runner/test_plugin_parsers.py`
- Modify: `tests/unit/lb_ui/test_cleanup_policy.py`
- Modify: `tests/unit/lb_ui/test_cli.py`
- Modify: `tests/unit/lb_ui/test_cli_docker_status.py`
- Modify: `tests/unit/lb_ui/test_cli_run_summary.py`
- Modify: `tests/unit/lb_ui/test_cli_runs_analyze.py`
- Modify: `tests/unit/lb_ui/test_dashboard_rollup.py`
- Modify: `tests/unit/lb_ui/test_headless_hierarchical_picker.py`
- Modify: `tests/unit/lb_ui/test_interactive_selection.py`
- Modify: `tests/unit/lb_ui/test_notifier.py`
- Modify: `tests/unit/lb_ui/test_picker_crash.py`
- Modify: `tests/unit/lb_ui/test_tui_public_api.py`
- Modify: `tests/unit/lint/test_import_boundaries.py`
- Modify: `tests/unit/test_interrupts.py`
- Modify: `tests/unit/test_log_streaming.py`

**Step 1: Targeted lint check**

Run: `uv run flake8 tests --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: FAIL.

**Step 2: Fix formatting and complexity**

Resolve whitespace/indentation issues, E501, and CCR001; refactor only.

**Step 3: Re-run targeted lint**

Run: `uv run flake8 tests --select E501,W291,W292,W293,W391,E302,E303,E304,E111,E117,CCR001,I250`
Expected: PASS.

**Step 4: Commit**

Run:
```bash
git add tests
git commit -m "Fix flake8 issues in tests"
```

### Task 13: Final Verification

**Files:**
- Modify: none
- Test: `.` (full repo)

**Step 1: Full flake8 run**

Run: `uv run flake8 .`
Expected: PASS (no output).

**Step 2: Commit (if needed)**

Run:
```bash
git add .
git commit -m "Fix remaining flake8 issues"
```
