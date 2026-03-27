# Rich TUI Premium Restyle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refresh the entire `lb_ui` terminal surface with a premium graphite-and-teal visual hierarchy while keeping behavior stable.

**Architecture:** Keep the existing `lb_ui` TUI structure intact and concentrate changes inside the shared theme layer plus the Rich dashboard, presenter, table, picker, and form surfaces. The journal remains the primary panel, while every other terminal surface adopts the same restrained chrome so the UI feels cohesive rather than a mix of old and new styling.

**Tech Stack:** Python 3.13, Rich, pytest

---

### Task 1: Baseline and Red Tests

**Files:**
- Modify: `tests/unit/lb_ui/test_tui_theme.py`
- Modify: `tests/unit/lb_ui/test_dashboard_rendering.py`
- Test: `tests/unit/lb_ui/test_dashboard_helpers.py`

**Step 1: Run the current focused baseline**

Run:

```bash
uv run pytest tests/unit/lb_ui/test_tui_theme.py tests/unit/lb_ui/test_dashboard_helpers.py tests/unit/lb_ui/test_dashboard_rendering.py -m unit_ui
```

Expected: PASS on the current worktree baseline.

**Step 2: Add failing tests for the premium hierarchy**

Add assertions that capture the intended aesthetic rules:

- the theme exposes distinct title styles for primary and secondary surfaces
- presenter rules/panels use the secondary border style
- dashboard log/status empty states use muted copy instead of blank raw output

**Step 3: Run the focused tests and confirm RED**

Run:

```bash
uv run pytest tests/unit/lb_ui/test_tui_theme.py tests/unit/lb_ui/test_dashboard_rendering.py -m unit_ui
```

Expected: FAIL only on the newly added assertions.

### Task 2: Shared Theme and Presenter Restyle

**Files:**
- Modify: `lb_ui/tui/core/theme.py`
- Modify: `lb_ui/tui/system/components/presenter.py`

**Step 1: Implement the minimal theme additions**

Add only the helpers/constants required by the failing tests:

- stronger distinction between primary/secondary titles
- muted body/placeholder styling helpers
- rule styling aligned with the graphite-and-teal palette

**Step 2: Apply the shared presenter styling**

Keep presenter behavior unchanged, but ensure panels and rules inherit the refined secondary treatment.

**Step 3: Run the focused tests**

Run:

```bash
uv run pytest tests/unit/lb_ui/test_tui_theme.py -m unit_ui
```

Expected: PASS.

### Task 3: Dashboard Restyle

**Files:**
- Modify: `lb_ui/tui/system/components/dashboard.py`
- Modify: `lb_ui/tui/system/components/dashboard_helpers.py`
- Modify: `tests/unit/lb_ui/test_dashboard_rendering.py`

**Step 1: Implement the premium dashboard treatment**

Refine only presentation:

- cleaner journal/log/status titles
- muted empty states instead of blank filler lines
- tighter log rendering with subdued timing metadata
- more intentional table spacing/placeholder styling

**Step 2: Run the dashboard tests**

Run:

```bash
uv run pytest tests/unit/lb_ui/test_dashboard_helpers.py tests/unit/lb_ui/test_dashboard_rendering.py -m unit_ui
```

Expected: PASS.

### Task 4: Presenter, Table, Picker, and Form Restyle

**Files:**
- Modify: `lb_ui/tui/system/components/presenter.py`
- Modify: `lb_ui/tui/system/components/table.py`
- Modify: `lb_ui/tui/system/components/table_layout.py`
- Modify: `lb_ui/tui/system/components/form.py`
- Modify: `lb_ui/tui/system/components/flat_picker_panel.py`
- Modify: `lb_ui/tui/screens/picker_screen.py`
- Modify: `tests/unit/lb_ui/test_picker_screen.py`
- Create: `tests/unit/lb_ui/test_tui_components.py`

**Step 1: Add failing tests for the remaining TUI surfaces**

Cover:

- presenter panels/rules reuse the secondary chrome
- table presenter uses quieter table chrome
- forms pass styled prompts to Rich
- picker breadcrumbs and row copy match the premium palette/copy choices

**Step 2: Run the focused tests and confirm RED**

Run:

```bash
uv run pytest tests/unit/lb_ui/test_picker_screen.py tests/unit/lb_ui/test_tui_components.py -m unit_ui
```

Expected: FAIL only on the newly added assertions.

**Step 3: Implement the restyle across the remaining TUI surfaces**

Keep behavior unchanged; change only styling, copy, and structural presentation.

**Step 4: Run the focused tests**

Run:

```bash
uv run pytest tests/unit/lb_ui/test_picker_screen.py tests/unit/lb_ui/test_tui_components.py -m unit_ui
```

Expected: PASS.

### Task 5: Final Verification

**Files:**
- Verify only

**Step 1: Run the full focused verification set**

Run:

```bash
uv run pytest tests/unit/lb_ui/test_tui_theme.py tests/unit/lb_ui/test_dashboard_helpers.py tests/unit/lb_ui/test_dashboard_rendering.py tests/unit/lb_ui/test_picker_screen.py tests/unit/lb_ui/test_tui_components.py tests/unit/lb_ui/test_cli.py -m unit_ui
```

Expected: PASS.

**Step 2: Review diff for scope**

Run:

```bash
git diff --stat
git diff -- lb_ui/tui/core/theme.py lb_ui/tui/system/components/presenter.py lb_ui/tui/system/components/table.py lb_ui/tui/system/components/table_layout.py lb_ui/tui/system/components/form.py lb_ui/tui/system/components/flat_picker_panel.py lb_ui/tui/screens/picker_screen.py lb_ui/tui/system/components/dashboard.py lb_ui/tui/system/components/dashboard_helpers.py tests/unit/lb_ui/test_tui_theme.py tests/unit/lb_ui/test_dashboard_rendering.py tests/unit/lb_ui/test_picker_screen.py tests/unit/lb_ui/test_tui_components.py
```

Expected: only aesthetic Rich TUI changes plus matching tests/plan.
