# Remediation of the 2026-09-11 audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tool tell the truth — a failed run must not report success, the interactive selection must not corrupt the config, and the metric collectors must not silently abort or silently lose data.

**Architecture:** Nine independent fixes, each with its own failing test first. Five are Python fixes confined to `lb_ui/` and `lb_runner/`; three are Ansible and `.ansible-lint` changes; one is a pure refactor of `lb_provisioner` that makes the emitted argv testable (the prerequisite for any later SDK migration).

**Tech Stack:** Python 3.12+ (CI also runs 3.13), pytest with `--strict-markers`, ruff 0.16.6, basedpyright in standard mode, bandit, ansible-lint, deptry, import-linter. Dependency management with `uv`.

**Spec:** The audit findings produced in this session. Each task below quotes the evidence it fixes; the `file:line` references are the source of truth and were verified by hand before writing this plan.

## Global Constraints

- Python floor is **3.12**; CI runs 3.12 and 3.13.
- **Every test needs a marker** — pytest runs with `--strict-markers`. Use `pytest.mark.unit_ui` for `lb_ui`, `pytest.mark.unit_runner` for `lb_runner`, `pytest.mark.unit_provisioner` for `lb_provisioner`. A module-level `pytestmark = pytest.mark.unit_x` covers the whole file.
- `uv run --frozen ruff check .` and `uv run --frozen basedpyright` must both be clean; `basedpyright` must stay at **0 errors, 0 warnings**.
- Formatting is `uv run --frozen ruff format .` (88 columns).
- Coverage gate is **67%** overall (`[tool.coverage.report] fail_under`). Adding tests only helps.
- Never import package internals from another package — use `lb_<pkg>.api`. Enforced by ruff `TID251` and import-linter.
- Commit messages: present tense, imperative. End every commit with:
  `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- Run the suite the way CI does:
  `QT_QPA_PLATFORM=offscreen xvfb-run -a uv run --frozen pytest tests/unit tests/integration -m "not slow and not slowest and not inter_docker" --cov`
- Do **not** modify anything under `molecule/ansible/collections/` or `lb_plugins/plugins/_user/`; both are excluded on purpose.

---

## Task 1: `lb run` must not report success when the run never started

A `None` from `start_run` overwrites the failure flag, so the CLI exits 0, prints "Run completed." in green, and sends a success notification.

**Files:**
- Modify: `lb_ui/cli/commands/run.py:250-252` (the `run_result` assignment) and insert a guard after the `finally:` block that ends near `:275`
- Test: `tests/unit/lb_ui/test_cli.py` (append at end of file)

**Interfaces:**
- Consumes: `lb_app.api.ApplicationClient.start_run(request, hooks) -> RunResult | None`. It returns `None` at `lb_app/client.py:255` (connectivity check failed) and `:269` (`ProvisioningError`).
- Produces: nothing new. The CLI command now exits 1 on that path.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/lb_ui/test_cli.py`:

```python
@pytest.mark.unit_ui
def test_run_reports_failure_when_start_run_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A run that never started must not exit 0 with a SUCCESS notification.

    start_run returns None when the connectivity check fails or provisioning is
    rejected. run used to overwrite its own failure flag unconditionally, so
    that path exited 0 and announced success.
    """
    cli = _load_cli(monkeypatch, tmp_path)

    cfg = BenchmarkConfig()
    _ensure_workload_enabled(cfg, "stress_ng")
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)

    monkeypatch.setattr(
        cli.app_client,
        "_provision",
        lambda config, execution_mode, node_count, docker_engine=None, resume=None: (
            config,
            None,
        ),
    )
    monkeypatch.setattr(cli.app_client, "start_run", lambda *_args, **_kwargs: None)

    result = CliRunner().invoke(
        cli.app,
        ["run", "-c", str(cfg_path), "--run-id", "no-connectivity"],
    )

    assert result.exit_code == 1, result.output
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --frozen pytest tests/unit/lb_ui/test_cli.py::test_run_reports_failure_when_start_run_returns_none -v --no-cov`
Expected: FAIL — `assert 0 == 1`.

- [ ] **Step 3: Implement**

In `lb_ui/cli/commands/run.py`, replace the unconditional success flag:

```python
            run_result = ctx.app_client.start_run(run_request, _Hooks())
            result = run_result
            run_success = run_result is not None
```

Then, immediately after the `finally:` block (before the `if (result and result.journal_path ...)` check), insert:

```python
        if not run_success:
            ctx.ui.present.error(
                "Run did not start: start_run returned no result "
                "(connectivity or provisioning failed)."
            )
            raise typer.Exit(1)
```

This leaves the `finally:` block intact, so the tray still stops and the notification is sent with `success=False` and the word `FAILED`.

- [ ] **Step 4: Run the test and the rest of the CLI tests**

Run: `uv run --frozen pytest tests/unit/lb_ui/test_cli.py -v --no-cov`
Expected: all PASS, including `test_run_command_exists` (that one patches the internals so `start_run` still returns a truthy result).

- [ ] **Step 5: Commit**

```bash
git add lb_ui/cli/commands/run.py tests/unit/lb_ui/test_cli.py
git commit -m "Exit non-zero when lb run never started

start_run returns None when connectivity or provisioning fails, but run
overwrote run_success unconditionally, so that path exited 0, printed
\"Run completed.\" and sent a success notification. Guard on the result and
exit 1, keeping the finally block so the tray still stops."
```

---

## Task 2: Interactive selection must record the workload name, not the intensity label

`pick_many` returns the selected **variant**, whose `id` is the bare intensity (`"medium"`), but the consumer expects `"<workload>:<intensity>"`. So the `if ":" in picked.id` branch never fires, the real workload is deleted and a bogus `WorkloadConfig(plugin="medium")` is written.

**Files:**
- Modify: `lb_ui/flows/selection.py:65` (the variant `PickItem` constructor)
- Test: create `tests/unit/lb_ui/test_selection_flow.py`

**Interfaces:**
- Consumes: `lb_ui.tui.system.models.PickItem`; `PickerSelectionState.build_result` returns `item.variants[variant_idx]` verbatim (`lb_ui/tui/screens/picker_screen.py:89-96`), which `tests/unit/lb_ui/test_picker_screen.py:27` asserts.
- Produces: variant ids of the form `"<workload_name>:<intensity_id>"`, which the existing `base, level = picked.id.split(":", 1)` at `selection.py:142` already parses.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/lb_ui/test_selection_flow.py`:

```python
"""Tests for the interactive workload selection flow."""

from pathlib import Path

import pytest

from lb_app.api import BenchmarkConfig, ConfigService, PluginRegistry, WorkloadConfig
from lb_ui.flows import selection as selection_mod
from lb_ui.flows.selection import select_workloads_interactively

pytestmark = pytest.mark.unit_ui


class _FakePicker:
    """Returns the chosen workload's selected *variant*, like the real picker."""

    def __init__(self, workload: str, variant_index: int = 2) -> None:
        self.workload = workload
        self.variant_index = variant_index
        self.seen_items = []

    def pick_many(self, items, title=None):
        self.seen_items = list(items)
        for item in items:
            if item.id == self.workload:
                return [item.variants[self.variant_index]]
        raise AssertionError(
            f"item {self.workload!r} not offered: {[i.id for i in items]}"
        )


class _FakeUI:
    def __init__(self, picker) -> None:
        self.picker = picker
        self.present = _FakePresent()


class _FakePresent:
    def warning(self, *_a, **_k):
        return None

    def success(self, *_a, **_k):
        return None

    def info(self, *_a, **_k):
        return None

    def error(self, *_a, **_k):
        return None


def test_picking_a_workload_records_its_name(monkeypatch, tmp_path: Path):
    """Picking "stream" with the medium variant must keep the workload named
    "stream" and set its intensity, not create a workload called "medium"."""
    monkeypatch.setattr(selection_mod, "is_tty_available", lambda: True)
    config_service = ConfigService()

    cfg_path = tmp_path / "cfg.json"
    cfg = BenchmarkConfig()
    cfg.workloads["stream"] = WorkloadConfig(plugin="stream", options={})
    cfg.save(cfg_path)

    ui = _FakeUI(_FakePicker("stream"))
    registry = PluginRegistry()

    select_workloads_interactively(
        ui, config_service, cfg, registry, cfg_path, set_default=False
    )

    saved = BenchmarkConfig.load(cfg_path)
    assert "stream" in saved.workloads, sorted(saved.workloads)
    assert "medium" not in saved.workloads, sorted(saved.workloads)
    assert saved.workloads["stream"].intensity == "medium"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --frozen pytest tests/unit/lb_ui/test_selection_flow.py -v --no-cov`
Expected: FAIL — `assert 'stream' in saved.workloads` fails; the saved config has `{"medium": ...}` instead.

If the test errors earlier (missing plugin registry entry, or `BenchmarkConfig.load` is not the right API), fix the test harness — not the assertion. The failure must be the workload-name assertion.

- [ ] **Step 3: Implement**

In `lb_ui/flows/selection.py`, inside the `for variant in intensities_catalog:` loop, change the variant id to a composite:

```python
            variant_list.append(
                PickItem(
                    id=f"{name}:{variant.id}",
                    title=label,
                    description=desc,
                    payload=variant.payload,
                    tags=variant.tags,
                    search_blob=variant.search_blob or label,
                    preview=variant.preview,
                    selected=variant.id == current_intensity,
                )
            )
```

Only the `id=` line changes. `variant.id == current_intensity` still compares against the original, un-prefixed id, so preselection keeps working.

- [ ] **Step 4: Run the test and the neighbouring UI tests**

Run: `uv run --frozen pytest tests/unit/lb_ui/test_selection_flow.py tests/unit/lb_ui/test_picker_screen.py tests/unit/lb_ui/test_picker_preselection.py tests/unit/lb_ui/test_interactive_selection.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lb_ui/flows/selection.py tests/unit/lb_ui/test_selection_flow.py
git commit -m "Record the workload name when selecting interactively

pick_many returns the selected variant, whose id was the bare intensity
(\"medium\"), but the consumer parses \"<workload>:<intensity>\". The composite
branch never fired, so the flow deleted the real workload and wrote
WorkloadConfig(plugin=\"medium\"). Give variants a composite id."
```

---

## Task 3: A missing optional CLI tool must not abort the whole run

`_validate_environment` returns `False` on the **first** missing tool. `BaseCollector.start` then raises `MetricCollectionError`, and `RepetitionExecutor.execute` calls `metric_session.start()` **before** `generator.start()` — so on a host without `sysstat` (4 of the 5 default commands) no repetition ever runs the workload.

**Files:**
- Modify: `lb_runner/metric_collectors/cli_collector.py:155-168` (`_validate_environment`)
- Test: `tests/unit/lb_runner/test_cli_collector.py` (append)

**Interfaces:**
- Consumes: `CLICollector.__init__(name="CLICollector", interval_seconds=5.0, commands=None)`; `_is_tool_available(tool) -> bool` (currently `subprocess.run(["which", tool])`).
- Produces: `_validate_environment()` now **mutates** `self.commands` to drop unavailable entries and returns `True` while at least one remains; returns `False` only when none remain. No other module reads `self.commands` after start, and `builtin.py:60` passes the configured list in.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/lb_runner/test_cli_collector.py`:

```python
from lb_runner.metric_collectors.cli_collector import CLICollector


def test_missing_optional_tool_is_dropped_not_fatal(monkeypatch):
    """One unavailable tool must not stop the collector using the others."""
    monkeypatch.setattr(
        CLICollector,
        "_is_tool_available",
        lambda self, tool: tool == "vmstat",
    )
    collector = CLICollector(
        interval_seconds=1.0,
        commands=["vmstat 1 1", "definitely-not-a-tool 1 1"],
    )

    assert collector._validate_environment() is True
    assert collector.commands == ["vmstat 1 1"]


def test_no_available_tool_is_still_fatal(monkeypatch):
    """With nothing left to run, the collector cannot start."""
    monkeypatch.setattr(CLICollector, "_is_tool_available", lambda self, tool: False)
    collector = CLICollector(interval_seconds=1.0, commands=["vmstat 1 1"])

    assert collector._validate_environment() is False
```

`CLICollector` is deliberately not exported from `lb_runner.api`, so import it from its module. Do not add an export just for a test.

- [ ] **Step 2: Run them and watch the first fail**

Run: `uv run --frozen pytest tests/unit/lb_runner/test_cli_collector.py -v --no-cov`
Expected: `test_missing_optional_tool_is_dropped_not_fatal` FAILS (`assert False is True`); `test_no_available_tool_is_still_fatal` passes already.

- [ ] **Step 3: Implement**

Replace `_validate_environment` in `lb_runner/metric_collectors/cli_collector.py`:

```python
    def _validate_environment(self) -> bool:
        """Drop commands whose tool is missing, keeping the ones that work.

        A missing *optional* tool must not abort the benchmark: the metrics it
        would have produced are worth less than the workload run itself. The
        collector is only unusable when nothing at all is left to run.

        Returns:
            True if at least one command can run, False otherwise

        """
        usable = []
        for command in self.commands:
            tool = command.split()[0]
            if self._is_tool_available(tool):
                usable.append(command)
            else:
                logger.warning(
                    "Skipping CLI metric command '%s': tool '%s' is not available",
                    command,
                    tool,
                )

        if not usable:
            logger.error("No CLI metric command can run in this environment")
            return False

        self.commands = usable
        return True
```

- [ ] **Step 4: Run the collector tests and the executor tests**

Run: `uv run --frozen pytest tests/unit/lb_runner -k "collector or executor" -v --no-cov`
Expected: all PASS. If a test asserts the old all-or-nothing behaviour, read it before changing it — it is asserting the bug.

- [ ] **Step 5: Commit**

```bash
git add lb_runner/metric_collectors/cli_collector.py tests/unit/lb_runner/test_cli_collector.py
git commit -m "Skip unavailable CLI metric tools instead of aborting the run

_validate_environment failed closed on the first missing tool, and the executor
starts the metric session before the generator, so a host without sysstat never
ran the workload at all. Drop what cannot run, keep what can, and only fail when
nothing is left."
```

---

## Task 4: Stop silently discarding every row after the first

`_collect_metrics` does `parsed = parsed[0] if ... else {}`. `jc` returns one dict **per device**, so `iostat -d 1 1` keeps only the first device and drops the rest without a word.

**Files:**
- Modify: `lb_runner/metric_collectors/cli_collector.py:91` (the list narrowing) — extract it into a module-level pure function
- Test: `tests/unit/lb_runner/test_cli_collector.py` (append)

**Interfaces:**
- Produces: module-level `_merge_parsed(tool_name: str, parsed: Any) -> dict[str, Any]`. For a list of one dict it returns that dict (unchanged behaviour). For a list of more than one dict it returns the first row's keys **plus** the full list under `f"{tool_name}_rows"`. For anything else it returns `{}`.
- `_collect_metrics` calls it and passes the result to `metrics.update(...)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/lb_runner/test_cli_collector.py`:

```python
from lb_runner.metric_collectors.cli_collector import _merge_parsed


def test_single_row_list_is_merged_flat():
    """One row keeps the flat schema the aggregators expect."""
    assert _merge_parsed("vmstat", [{"runnable_procs": 1}]) == {"runnable_procs": 1}


def test_multi_row_list_keeps_every_row():
    """jc returns one dict per device; none of them may be dropped."""
    rows = [
        {"device": "loop0", "tps": 1.0},
        {"device": "nvme0n1", "tps": 79.42},
    ]

    merged = _merge_parsed("iostat", rows)

    assert merged["device"] == "loop0"
    assert merged["iostat_rows"] == rows


def test_non_list_passes_through():
    assert _merge_parsed("sar", {"user_time": 5}) == {"user_time": 5}
    assert _merge_parsed("sar", None) == {}
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run --frozen pytest tests/unit/lb_runner/test_cli_collector.py -v --no-cov`
Expected: `ImportError: cannot import name '_merge_parsed'`.

- [ ] **Step 3: Implement**

Add near the top of `lb_runner/metric_collectors/cli_collector.py`, after the logger:

```python
def _merge_parsed(tool_name: str, parsed: Any) -> dict[str, Any]:
    """Flatten one command's jc output into metrics without losing rows.

    jc returns one dict per device or per CPU, so a multi-row result cannot be
    flattened into a single dict without collision. The first row is merged flat
    so the existing aggregator schema keeps working, and every row is preserved
    under ``<tool>_rows`` so nothing is silently discarded.

    Args:
        tool_name: Name of the tool, used to namespace the per-row detail
        parsed: Whatever jc returned

    Returns:
        A flat dict of metrics

    """
    if isinstance(parsed, list):
        rows = [row for row in parsed if isinstance(row, dict)]
        if not rows:
            return {}
        if len(rows) > 1:
            logger.warning(
                "Command '%s' produced %d rows; keeping the first flat and all "
                "of them under '%s_rows'",
                tool_name,
                len(rows),
                tool_name,
            )
            return {**rows[0], f"{tool_name}_rows": rows}
        return dict(rows[0])
    if isinstance(parsed, dict):
        return dict(parsed)
    return {}
```

Then in `_collect_metrics`, replace:

```python
                if isinstance(parsed, list):
                    parsed = parsed[0] if parsed and isinstance(parsed[0], dict) else {}
                if isinstance(parsed, dict):
                    metrics.update(parsed)
```

with:

```python
                metrics.update(_merge_parsed(tool_name, parsed))
```

- [ ] **Step 4: Run the tests**

Run: `uv run --frozen pytest tests/unit/lb_runner -k "collector or aggreg" -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lb_runner/metric_collectors/cli_collector.py tests/unit/lb_runner/test_cli_collector.py
git commit -m "Keep every row of a multi-row metric result

jc returns one dict per device, and _collect_metrics kept only the first,
so iostat reported a single disk and lost the others without a word. Merge the
first row flat for schema compatibility and keep all rows under <tool>_rows."
```

---

## Task 5: `aggregate_cli` must understand the current `jc` key names

The aggregator matches `"r"`, `"b"`, `"si"`, `"so"`. `jc` 1.25 (the pinned version) emits `runnable_procs`, `uninterruptible_sleeping_procs`, `swap_in`, `swap_out`, so the function returns `{}` for every real run.

**Files:**
- Modify: `lb_runner/metric_collectors/aggregators.py:70-81`
- Test: `tests/unit/lb_runner/test_cli_collector.py` (append) — this is where the existing `aggregate_cli` tests live

**Interfaces:**
- Produces: `aggregate_cli(df)` keeps returning the same four metric names (`processes_running_avg`, `processes_blocked_avg`, `swap_in_kbps_avg`, `swap_out_kbps_avg`) and still accepts the legacy column names.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/lb_runner/test_cli_collector.py`:

```python
def test_aggregate_cli_handles_current_jc_column_names():
    """jc 1.25 renamed the vmstat keys; the aggregator must still summarise.

    Verified against jc 1.25.6: its vmstat parser emits runnable_procs,
    uninterruptible_sleeping_procs, swap_in and swap_out.
    """
    df = pd.DataFrame(
        [
            {
                "runnable_procs": 1,
                "uninterruptible_sleeping_procs": 0,
                "swap_in": 5.0,
                "swap_out": 2.0,
            },
            {
                "runnable_procs": 3,
                "uninterruptible_sleeping_procs": 1,
                "swap_in": 7.0,
                "swap_out": 4.0,
            },
        ]
    )

    result = aggregate_cli(df)

    assert result["processes_running_avg"] == 2.0
    assert result["processes_blocked_avg"] == 0.5
    assert result["swap_in_kbps_avg"] == 6.0
    assert result["swap_out_kbps_avg"] == 3.0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --frozen pytest tests/unit/lb_runner/test_cli_collector.py::test_aggregate_cli_handles_current_jc_column_names -v --no-cov`
Expected: FAIL with `KeyError: 'processes_running_avg'` — the function returns `{}`.

- [ ] **Step 3: Implement**

At module level in `lb_runner/metric_collectors/aggregators.py`:

```python
# jc renamed the vmstat/sar keys in 1.25 (r -> runnable_procs, si -> swap_in, ...).
# Match the current names first and fall back to the legacy ones so data
# collected before and after the rename aggregates the same way.
_CLI_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "processes_running_avg": ("runnable_procs", "r"),
    "processes_blocked_avg": ("uninterruptible_sleeping_procs", "b"),
    "swap_in_kbps_avg": ("swap_in", "si"),
    "swap_out_kbps_avg": ("swap_out", "so"),
}
```

and replace the four `if "<col>" in df.columns:` blocks with:

```python
    for metric, candidates in _CLI_COLUMN_ALIASES.items():
        for column in candidates:
            if column in df.columns:
                summary[metric] = df[column].mean()
                break
```

Also update the module docstring if it names the old columns.

- [ ] **Step 4: Run the aggregator tests**

Run: `uv run --frozen pytest tests/unit/lb_runner -k "aggreg" -v --no-cov`
Expected: all PASS, including the pre-existing legacy-name tests `test_aggregate_cli_handles_numeric_columns` and `test_aggregate_cli_ignores_non_numeric` — those must keep passing, they are the backwards-compatibility guarantee.

- [ ] **Step 5: Commit**

```bash
git add lb_runner/metric_collectors/aggregators.py tests/unit/lb_runner/test_cli_collector.py
git commit -m "Aggregate CLI metrics under the current jc key names

Aggregate_cli matched only the pre-1.25 keys (r, b, si, so), so with the pinned
jc it returned an empty summary for every real collection. Accept both spellings,
counting on the existing legacy tests as the compatibility guarantee."
```

---

## Task 6: Stop masking download failures in the Ansible shell pipelines

Fourteen tasks run `curl ... | sh`. A pipeline's exit status is the **last** command's, so a failed download still yields `rc=0` and a `changed` task: the failure surfaces later as an unrelated error ("Copy kubeconfig: source not found").

**Files (all 14 sites, enumerated — 3 shapes):**

Shape A — k3s, `curl -sfL https://get.k3s.io | sh -`, `creates: /usr/local/bin/k3s`:
- Modify: `lb_plugins/plugins/dfaas/ansible/setup_target.yml:27`
- Modify: `lb_plugins/plugins/dfaas/ansible/tasks/setup_target_tasks.yml:13`
- Modify: `lb_plugins/plugins/peva_faas/ansible/setup_target.yml:27`
- Modify: `lb_plugins/plugins/peva_faas/ansible/tasks/setup_k3s_tasks.yml:13`

Shape B — helm, `curl -sSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash`, `creates: "/usr/local/bin/helm"`:
- Modify: `lb_plugins/plugins/dfaas/ansible/setup_target.yml:48`
- Modify: `lb_plugins/plugins/dfaas/ansible/tasks/setup_target_tasks.yml:34`
- Modify: `lb_plugins/plugins/peva_faas/ansible/setup_target.yml:48`
- Modify: `lb_plugins/plugins/peva_faas/ansible/tasks/setup_k3s_tasks.yml:34`

Shape C — OpenFaaS CLI, `curl -sSL https://cli.openfaas.com | sh`, `creates: /usr/local/bin/faas-cli`:
- Modify: `lb_plugins/plugins/dfaas/ansible/setup_target.yml:53`
- Modify: `lb_plugins/plugins/dfaas/ansible/tasks/setup_target_tasks.yml:39`
- Modify: `lb_plugins/plugins/peva_faas/ansible/setup_plugin.yml:43`
- Modify: `lb_plugins/plugins/peva_faas/ansible/setup_k6.yml:16`
- Modify: `lb_plugins/plugins/peva_faas/ansible/setup_target.yml:53`
- Modify: `lb_plugins/plugins/peva_faas/ansible/tasks/setup_k3s_tasks.yml:39`

Four sites for `get.k3s.io`, four for `get-helm-3`, six for `cli.openfaas.com`.

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: no variable or task-name changes. `creates:` is preserved on every task so idempotence is unchanged.

- [ ] **Step 1: Replace the k3s sites (Shape A, 4 sites)**

Each currently reads:

```yaml
    - name: Install k3s
      ansible.builtin.shell: "curl -sfL https://get.k3s.io | sh -"
      args:
        creates: /usr/local/bin/k3s
```

Replace with:

```yaml
    - name: Download the k3s installer
      ansible.builtin.get_url:
        url: https://get.k3s.io
        dest: /tmp/install-k3s.sh
        mode: "0755"

    - name: Install k3s
      ansible.builtin.command:
        cmd: /tmp/install-k3s.sh
      args:
        creates: /usr/local/bin/k3s
```

- [ ] **Step 2: Replace the OpenFaaS CLI sites (Shape C, 6 sites)**

Replace with:

```yaml
    - name: Download the OpenFaaS CLI installer
      ansible.builtin.get_url:
        url: https://cli.openfaas.com
        dest: /tmp/install-openfaas-cli.sh
        mode: "0755"

    - name: Install the OpenFaaS CLI
      ansible.builtin.command:
        cmd: /tmp/install-openfaas-cli.sh
      args:
        creates: /usr/local/bin/faas-cli
```

Check the current `creates:` path at each site before writing it — if a site guards on a different path, keep that path.

- [ ] **Step 3: Replace the helm sites (Shape B, 4 sites)**

Replace with:

```yaml
    - name: Download the helm installer
      ansible.builtin.get_url:
        url: https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
        dest: /tmp/get-helm-3.sh
        mode: "0755"

    - name: Install helm
      ansible.builtin.command:
        cmd: /tmp/get-helm-3.sh
      args:
        creates: "/usr/local/bin/helm"
```

`get_url` fails the task on a non-2xx response, so the download failure is now attributed to the download — which is the whole point.

- [ ] **Step 4: Check the files still parse and lint**

Run: `uv run --frozen ansible-lint -f pep8 --nocolor 2>&1 | tail -5; echo "exit=$?"`
Expected: exit 0. The `risky-shell-pipe` count should fall from 22; `no-changed-when` may fall too, since `command` with `creates:` is change-aware.

Run: `uv run --frozen yamllint -c .yamllint.yaml lb_plugins/`
Expected: no new findings.

- [ ] **Step 5: Verify the pipeline claim the fix is built on**

Run: `/bin/sh -c 'false | sh'; echo "pipe exit=$?"` then `set -o pipefail; false | sh; echo "pipefail exit=$?"`
Expected: `0` then `1`. This is the evidence that the old form hid the failure; if it prints anything else, stop and re-read the Ansible tasks before continuing.

- [ ] **Step 6: Commit**

```bash
git add lb_plugins/plugins/dfaas/ansible lb_plugins/plugins/peva_faas/ansible
git commit -m "Stop masking download failures behind a shell pipeline

Fourteen tasks ran 'curl ... | sh', and a pipeline's status is the last
command's, so a failed download still reported rc=0 and a change; the play then
died on an unrelated step. Download with get_url and execute the script, keeping
the existing creates: guards."
```

---

## Task 7: Keep the OpenFaaS admin password out of the process command line

`dfaas/ansible/setup_target.yml:110-117` passes the decoded cluster-admin password as `--password {{ openfaas_admin_password }}`, where `/proc/<pid>/cmdline` exposes it for the whole retry window (`retries: 10`, `delay: 6`), and no task in the tree sets `no_log`.

**Files:**
- Modify: `lb_plugins/plugins/dfaas/ansible/setup_target.yml:110-117`
- Modify: `lb_plugins/plugins/peva_faas/ansible/setup_target.yml` (the matching login task) and `lb_plugins/plugins/peva_faas/ansible/setup_plugin.yml` if it logs in too

**Interfaces:**
- Consumes: `openfaas_admin_password` (set by the `Decode OpenFaaS admin password` task) and `openfaas_gateway_url`, `openfaas_admin_user`.
- Produces: no new variables.

- [ ] **Step 1: Verify the flag exists before relying on it**

Run on a host with the CLI, or check the vendor documentation: `faas-cli login --help | grep -i "password"`
Expected: a `--password-stdin` option. **If it does not exist, stop** and report back — the fallback is to keep `--password` and rely on `no_log` alone, which is weaker but still removes the password from Ansible's own output.

- [ ] **Step 2: Rewrite the login task**

Replace the login task in `dfaas/ansible/setup_target.yml` with:

```yaml
    - name: Login to OpenFaaS
      ansible.builtin.command:
        argv:
          - faas-cli
          - login
          - --gateway
          - "{{ openfaas_gateway_url }}"
          - --username
          - "{{ openfaas_admin_user }}"
          - --password-stdin
          - --tls-no-verify
      args:
        stdin: "{{ openfaas_admin_password }}"
      register: faas_login
      no_log: true
      retries: 10
      delay: 6
      until: faas_login.rc == 0
```

`stdin:` writes the secret to the child's standard input, so it never appears in `argv`. `no_log: true` keeps it out of Ansible's own logs and out of the registered result.

Apply the same shape to the `peva_faas` login task.

- [ ] **Step 3: Add `no_log` to the tasks that materialise the secret**

Mark the `Decode OpenFaaS admin password` task (`no_log: true`) as well — `set_fact` with `b64decode` prints the decoded value in verbose runs otherwise.

- [ ] **Step 4: Confirm nothing greps for the old output shape**

Run: `grep -rn "faas_login\|openfaas_admin_password" --include="*.py" --include="*.yml" lb_plugins | grep -v "^./.venv"`
Expected: only the tasks you just edited consume `faas_login`. If some Python code reads `faas_login.stdout`, note it — `no_log` changes what lands there.

- [ ] **Step 5: Commit**

```bash
git add lb_plugins/plugins/dfaas/ansible lb_plugins/plugins/peva_faas/ansible
git commit -m "Keep the OpenFaaS admin password off the command line

faas-cli login took the password as an argument, so it was readable in
/proc/<pid>/cmdline for the whole retry window, and no task set no_log. Feed it
on stdin and mark the secret-bearing tasks no_log."
```

---

## Task 8: Tighten the ansible-lint ratchet and refresh its documentation

Three rules sit in `warn_list` but produce **zero** findings, so they are blocking at no cost. The counts in the config comment are stale (they claim 201; the real number is 183).

**Files:**
- Modify: `.ansible-lint` (the `warn_list` and the comment block above it)

**Interfaces:**
- Consumes: the ratchet policy already documented in the file: *"Remove a rule from warn_list once its backlog is cleared; the count is the target."*
- Produces: `yaml[indentation]`, `yaml[colons]` and `run-once[task]` become blocking.

- [ ] **Step 1: Confirm the three rules are genuinely at zero**

Run: `uv run --frozen ansible-lint -f pep8 --nocolor 2>/dev/null | awk -F': ' '{print $2}' | awk '{print $1}' | sort | uniq -c | sort -rn`
Expected: the list contains no `yaml[indentation]`, no `yaml[colons]`, no `run-once[task]`.

- [ ] **Step 2: Remove them from `warn_list`**

Delete these three lines from the `warn_list:` block:

```yaml
  - yaml[indentation]
  - yaml[colons]
  - run-once[task]
```

- [ ] **Step 3: Refresh the documented counts**

Rewrite the comment block's table so each rule shows its **measured** count, and delete the entries whose rules no longer fire. Keep the policy paragraph and the note that `run-once[task]` is advisory — but move that note to explain that the rule is now blocking *because* the project uses the default linear strategy where `run_once` is well defined, so a regression there deserves to fail.

- [ ] **Step 4: Verify the tightening is free**

Run: `uv run --frozen ansible-lint -f pep8 --nocolor >/tmp/al_after.txt 2>&1; echo "exit=$?"; wc -l </tmp/al_after.txt`
Expected: `exit=0` and the same line count as before the change (183). A non-zero exit means one of the three rules does fire — put that rule back and report which.

- [ ] **Step 5: Commit**

```bash
git add .ansible-lint
git commit -m "Make three cleared ansible-lint rules blocking

yaml[indentation], yaml[colons] and run-once[task] are in warn_list but produce
no findings, so the ratchet can hold them at zero cost. Refresh the per-rule
counts too: the comment claimed 201 findings, the tree now reports 183."
```

---

## Task 9: Make the provisioner's argv testable

The provisioner tests stub `_launch_vm`, `_get_ip_address` and `_destroy_vm` wholesale, so nothing asserts the command actually emitted — a dropped `--purge` or a forgotten `-p <port>:22` passes green. This is the prerequisite for any SDK migration.

**Files:**
- Modify: `lb_provisioner/providers/multipass.py` (extract `launch_argv`, `info_argv`, `delete_argv`)
- Modify: `lb_provisioner/providers/docker.py` (extract `run_container_argv`, `delete_container_argv`)
- Test: create `tests/unit/lb_provisioner/test_provider_argv.py`

**Interfaces:**
- Produces, in `lb_provisioner/providers/multipass.py`:
  - `launch_argv(vm_name: str, image: str) -> list[str]`
  - `info_argv(vm_name: str) -> list[str]`
  - `delete_argv(vm_name: str) -> list[str]`
- Produces, in `lb_provisioner/providers/docker.py`:
  - `run_container_argv(engine: str, name: str, host_port: int, image: str, init_script: str) -> list[str]`
  - `delete_container_argv(engine: str, name: str) -> list[str]`
- These are pure: no subprocess, no logging, no I/O.

- [ ] **Step 1: Read the current commands and write the failing tests**

Read the three call sites first (`multipass.py:119-140`, `:158-163`, and the delete call; `docker.py:142-158`) so the extracted builders reproduce them exactly. Then create `tests/unit/lb_provisioner/test_provider_argv.py`:

```python
"""The provisioners must emit the exact CLI they are documented to emit.

These pin the argv because the lifecycle tests stub the whole provision() body,
so nothing else would notice a dropped flag.
"""

import pytest

from lb_provisioner.providers.docker import delete_container_argv, run_container_argv
from lb_provisioner.providers.multipass import delete_argv, info_argv, launch_argv

pytestmark = pytest.mark.unit_provisioner


def test_launch_argv_pins_resources_and_name():
    argv = launch_argv("lb-vm-1", "lts")

    assert argv[:2] == ["multipass", "launch"]
    assert argv[2] == "lts"
    assert argv[argv.index("--name") + 1] == "lb-vm-1"
    assert argv[argv.index("--cpus") + 1] == "4"
    assert argv[argv.index("--disk") + 1] == "20G"
    assert argv[argv.index("--memory") + 1] == "8G"


def test_info_argv_asks_for_json():
    assert info_argv("lb-vm-1") == [
        "multipass",
        "info",
        "lb-vm-1",
        "--format",
        "json",
    ]


def test_delete_argv_purges():
    assert "--purge" in delete_argv("lb-vm-1")
    assert delete_argv("lb-vm-1")[:3] == ["multipass", "delete", "lb-vm-1"]


def test_run_container_argv_publishes_port_and_runs_init():
    argv = run_container_argv("docker", "lb-1", 2201, "ubuntu:24.04", "echo hi")

    assert argv[0] == "docker"
    assert argv[1] == "run"
    assert argv[2] == "-d"
    assert argv[argv.index("--name") + 1] == "lb-1"
    assert argv[argv.index("-p") + 1] == "2201:22"
    assert argv[-3:] == ["bash", "-c", "echo hi"]


def test_delete_container_argv_removes_by_name():
    assert delete_container_argv("docker", "lb-1") == ["docker", "rm", "-f", "lb-1"]
```

Adjust the last two assertions to the argv you actually read in the source — the point is that they assert the real command, not a guess. If `delete_argv` does not currently pass `--purge`, that is a finding: assert what it does today, and raise it rather than quietly "fixing" it here.

- [ ] **Step 2: Run and watch it fail**

Run: `uv run --frozen pytest tests/unit/lb_provisioner/test_provider_argv.py -v --no-cov`
Expected: `ImportError: cannot import name 'launch_argv'`.

- [ ] **Step 3: Implement the builders**

In `lb_provisioner/providers/multipass.py`, add module-level functions and have `_launch_vm`, `_get_ip_address` and `_destroy_vm` call them:

```python
def launch_argv(vm_name: str, image: str) -> list[str]:
    """Command that launches one benchmark VM."""
    return [
        "multipass",
        "launch",
        image,
        "--name",
        vm_name,
        "--cpus",
        "4",
        "--disk",
        "20G",
        "--memory",
        "8G",
    ]
```

`_launch_vm` becomes `cmd = launch_argv(vm_name, image)`, keeping the `lts` fallback exactly as it is (`fallback = cmd[:]; fallback[2] = "lts"`).

Add the other two multipass builders to the same module:

```python
def info_argv(vm_name: str) -> list[str]:
    """Command that reports one VM's state as JSON."""
    return ["multipass", "info", vm_name, "--format", "json"]


def delete_argv(vm_name: str) -> list[str]:
    """Command that deletes one VM and purges its storage."""
    return ["multipass", "delete", vm_name, "--purge"]
```

And in `lb_provisioner/providers/docker.py`:

```python
def run_container_argv(
    engine: str,
    name: str,
    host_port: int,
    image: str,
    init_script: str,
) -> list[str]:
    """Command that starts one benchmark container with sshd on ``host_port``."""
    return [
        engine,
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "--hostname",
        name,
        "-p",
        f"{host_port}:22",
        image,
        "bash",
        "-c",
        init_script,
    ]


def delete_container_argv(engine: str, name: str) -> list[str]:
    """Command that force-removes one container."""
    return [engine, "rm", "-f", name]
```

`run_*` replaces the `cmd = [...]` literal in the docker provision path and `delete_container_argv` replaces the `cmd = [engine, "rm", "-f", name]` literal in its cleanup; the surrounding `subprocess.run` calls keep their current flags (`check`, `capture_output`, `text`) unchanged.

- [ ] **Step 4: Run the new tests plus the existing provisioner suite**

Run: `uv run --frozen pytest tests/unit/lb_provisioner -v --no-cov`
Expected: all PASS. The lifecycle tests must be unaffected — they stub the methods these builders now feed.

- [ ] **Step 5: Commit**

```bash
git add lb_provisioner/providers/multipass.py lb_provisioner/providers/docker.py tests/unit/lb_provisioner/test_provider_argv.py
git commit -m "Extract the provisioner argv into pure functions

The lifecycle tests stub _launch_vm, _get_ip_address and _destroy_vm wholesale,
so no test asserted the emitted command and a dropped flag was invisible. Pull
the argv out of the subprocess calls and pin it."
```

---

## Final verification (after the last task)

- [ ] Run `uv run --frozen ruff check . && uv run --frozen ruff format --check .`
- [ ] Run `uv run --frozen basedpyright` — expect **0 errors, 0 warnings, 0 notes**
- [ ] Run the suite the way CI does:
  `QT_QPA_PLATFORM=offscreen xvfb-run -a uv run --frozen pytest tests/unit tests/integration -m "not slow and not slowest and not inter_docker" --cov --cov-report=term-missing`
  Expect exit 0 and coverage at or above 67%.
- [ ] Run `uv run --frozen pre-commit run --all-files` — expect every hook to pass with no `--fix` rewrites.
- [ ] Open one PR per task, or one PR for Parte 1 if the reviewer prefers it. Do not merge without a green CI.

---

## Piani successivi (non in questo piano)

Questi sono deliberatamente esclusi: sono sottosistemi diversi e meritano un piano ciascuno.

1. **Migrazione `lb_provisioner/providers/multipass.py` → `multipass-sdk`.** Dipende dal Task 9, che ne è il prerequisito. Guadagno concreto: `_get_ip_address` oggi ritorna appena l'IP è non vuoto senza verificare che la 22 accetti, e l'indirizzo va dritto ad Ansible; `wait_ready` dell'SDK fa esattamente quella probe. Restano da reimplementare il retry sull'immagine `lts` e la generazione delle chiavi.
2. **`azure-vm-sdk`: `AzureVM.stop()`/`restart()` sono no-op.** Verificato: `desired_state` compare solo come dichiarazione e come output in `_templates.py`, nessuna risorsa lo consuma, e `from_tofu_output` legge lo stato *richiesto*. Una VM "fermata" continua a girare e a fatturare. Va corretto **prima** di qualunque integrazione Azure in linux-benchmark-lib.
3. **Decisione su `xenon`.** Esce 1 oggi (blocchi C/D, modulo `selection.py` a C) ma non è in pre-commit né in CI: o si riporta a verde e si cabla, o si toglie dal sweep di `arch_audit.sh`. Nota: il Task 2 tocca `selection.py`, quindi il suo rank può cambiare.
4. **Triage dei reperti non verificati** dell'audit (una ventina): `hpl` usa una variabile non risolta nel messaggio di fail, `teardown.yml` maschera l'archiviazione con `ignore_errors`, `ansible_helpers._run_capture` non consulta il token di stop né passa un timeout, `ssh-keygen` si blocca sul prompt Overwrite, il resume di docker ricrea risorse già esistenti, il report testuale descrive l'asse sbagliato. Ognuno va verificato prima di diventare un task.
