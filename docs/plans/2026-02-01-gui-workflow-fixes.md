# GUI Workflow Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix critical GUI workflow issues including locking navigation during benchmark runs and handling application shutdown gracefully.

**Architecture:**
- **Navigation Locking:** The `MainWindow` will act as the state coordinator. When a run starts, it will disable the sidebar navigation to prevent state inconsistency. When the run finishes (success or failure), navigation will be restored.
- **Graceful Shutdown:** Implement `closeEvent` in `MainWindow` to intercept close requests. If a benchmark is running, warn the user that the process is active.

**Tech Stack:** Python, PySide6.

---

### Task 1: Lock Navigation During Run

**Files:**
- Modify: `lb_gui/windows/main_window.py`

**Step 1: Create reproduction/verification script (Manual)**
Since automated GUI tests require setup, we define a manual verification step.
1. Run `lb-gui`.
2. Go to "Run Setup".
3. Start a "Run" (ensure valid config).
4. Try to click "Dashboard", "Config", etc. in the sidebar.
5. **Expected (Current):** You can navigate away.
6. **Expected (Target):** Sidebar items are disabled or ignored.

**Step 2: Implement `_set_ui_busy` in `MainWindow`**

Modify `lb_gui/windows/main_window.py`:
- Add method `_set_ui_busy(self, busy: bool)`:
  - `self._sidebar.setEnabled(not busy)`
  - Ideally, change cursor to `WaitCursor` if busy.

**Step 3: Integrate into Run Flow**

Modify `_connect_run_flow` -> `on_start_run` in `lb_gui/windows/main_window.py`:
- Call `self._set_ui_busy(True)` before starting worker.

**Step 4: Handle Run Completion**

Modify `lb_gui/windows/main_window.py`:
- Add `_on_run_finished(self, success: bool, error: str)` slot.
- Call `self._set_ui_busy(False)`.
- Show error message if `!success`.
- Set `self._current_worker = None`.
- Update `on_start_run` to connect `worker.signals.finished` to `self._on_run_finished` (instead of directly to dashboard_vm, or chain them). *Note: DashboardVM also listens to finished, we can have multiple slots.*

**Step 5: Verify Fix**
- Rerun manual verification. Sidebar should be disabled during run.

---

### Task 2: Graceful Shutdown Warning

**Files:**
- Modify: `lb_gui/windows/main_window.py`

**Step 1: Implement `closeEvent`**

Modify `lb_gui/windows/main_window.py`:
- Override `closeEvent(self, event)`.
- Check `if hasattr(self, "_current_worker") and self._current_worker and self._current_worker.is_running()`.
- If running:
  - Show `QMessageBox.question` with "Benchmark in progress. Closing now may leave remote processes running. Force Close?".
  - If Yes (`QMessageBox.Yes`): `event.accept()`.
  - If No (`QMessageBox.No`): `event.ignore()`.
- Else: `event.accept()`.

**Step 2: Verify Fix**
1. Start a run.
2. Try to close the window (X button).
3. **Expected:** Warning dialog appears.
4. Click No -> Window stays open, run continues.
5. Click Yes -> Window closes.

---
