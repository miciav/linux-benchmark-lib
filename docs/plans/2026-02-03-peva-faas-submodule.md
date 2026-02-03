# PEVA-faas Submodule Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a new PEVA-faas plugin repo on GitHub, link it as a submodule, and update code/tests to use the new module path while keeping internal names as dfaas.

**Architecture:** Seed a new GitHub repo with the current dfaas plugin contents, add it as a submodule at lb_plugins/plugins/peva_faas, then update import paths and filesystem references to point to the new module path without changing plugin identifiers.

**Tech Stack:** Git/GitHub CLI, Python 3.12+, uv/pytest, existing lb_plugins plugin system.

### Task 1: Create and seed the GitHub repo

**Files:**
- Create: `/tmp/PEVA-faas` (local repo)
- Source: `lb_plugins/plugins/dfaas` (copy in)

**Step 1: Create the remote repo**

Run: `gh repo create miciav/PEVA-faas --public`
Expected: Repo created on GitHub.

**Step 2: Initialize local repo**

Run: `rm -rf /tmp/PEVA-faas && mkdir -p /tmp/PEVA-faas && cd /tmp/PEVA-faas && git init`
Expected: Empty git repo initialized.

**Step 3: Copy current plugin contents**

Run: `rsync -a --delete <worktree>/lb_plugins/plugins/dfaas/ /tmp/PEVA-faas/`
Expected: /tmp/PEVA-faas matches dfaas contents.

**Step 4: Commit and push**

Run:
- `cd /tmp/PEVA-faas`
- `git add .`
- `git commit -m "Initial import from dfaas"`
- `git branch -M main`
- `git remote add origin git@github.com:miciav/PEVA-faas.git`
- `git push -u origin main`

Expected: Repo has initial commit with dfaas content.

### Task 2: Add PEVA-faas as a submodule

**Files:**
- Modify: `.gitmodules`
- Remove: `lb_plugins/plugins/dfaas`
- Create: `lb_plugins/plugins/peva_faas` (submodule)

**Step 1: Remove local dfaas directory**

Run: `rm -rf lb_plugins/plugins/dfaas`
Expected: Directory removed from main repo.

**Step 2: Add submodule**

Run: `git submodule add git@github.com:miciav/PEVA-faas.git lb_plugins/plugins/peva_faas`
Expected: Submodule added and .gitmodules updated.

**Step 3: Commit submodule pointer**

Run:
- `git add .gitmodules lb_plugins/plugins/peva_faas`
- `git commit -m "Add PEVA-faas plugin submodule"`

Expected: Main repo records submodule.

### Task 3: Update import paths and file references

**Files:**
- Modify: `lb_plugins/**`, `lb_controller/**`, `lb_app/**`, `lb_ui/**`, `tests/**`, `docs/**`
- Modify: `lb_plugins/plugins/peva_faas/**` (inside submodule)

**Step 1: Find all module imports to update**

Run: `rg -n "lb_plugins\.plugins\.dfaas" lb_plugins lb_controller lb_app lb_ui tests docs`
Expected: List of files to update to `lb_plugins.plugins.peva_faas`.

**Step 2: Update filesystem path references**

Run: `rg -n "lb_plugins/plugins/dfaas" lb_plugins tests docs`
Expected: List of files to update to `lb_plugins/plugins/peva_faas`.

**Step 3: Apply changes**

Edit each file to replace the module path and filesystem path references.
- Keep internal identifiers like NAME = "dfaas" and config key "plugins.dfaas" unchanged.
- Update any hard-coded file paths to point to the new directory.

**Step 4: Commit main-repo path updates**

Run:
- `git add <changed files>`
- `git commit -m "Update dfaas module path to peva_faas"`

Expected: Main repo references new module path.

### Task 4: Update plugin internals inside submodule

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/config.py`
- Modify: any other file in submodule that hard-codes `lb_plugins/plugins/dfaas`

**Step 1: Find hard-coded paths**

Run: `rg -n "lb_plugins/plugins/dfaas" lb_plugins/plugins/peva_faas`
Expected: Files needing updates to peva_faas path.

**Step 2: Update paths**

Edit to use `lb_plugins/plugins/peva_faas` where appropriate (or use `Path(__file__).parent` if more robust).

**Step 3: Commit submodule changes**

Run:
- `cd lb_plugins/plugins/peva_faas`
- `git add <changed files>`
- `git commit -m "Fix PEVA-faas path references"`
- `git push`

Expected: Submodule repo updated.

### Task 5: Verify locally

**Files:**
- Test: `tests/unit/lb_plugins/dfaas/*` (imports updated)
- Test: `tests/gui/windows/test_main_window_workflow.py`

**Step 1: Initialize repo submodules**

Run: `git submodule update --init --recursive lb_gui`
Expected: lb_gui populated so GUI tests can import.

**Step 2: Run targeted tests**

Run:
- `uv run pytest tests/unit/lb_plugins/dfaas -v`
- `uv run pytest tests/gui/windows/test_main_window_workflow.py -v`

Expected: Tests pass or show actionable failures.

**Step 3: Commit any remaining fixes**

Run:
- `git add <files>`
- `git commit -m "Fix PEVA-faas path regressions"`

Expected: Clean commit history with path changes.
