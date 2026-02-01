# GUI Dashboard Progress + Stop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show live progress in the GUI Dashboard by wiring the real RunJournal and add a graceful Stop button in the sidebar.

**Architecture:** Add a GUI-specific UIAdapter + DashboardHandle that forwards core updates via Qt signals to the GUIDashboardViewModel. Pass this adapter into RunRequest so the core uses the real journal, and add a sidebar Stop button that touches the stop file for graceful teardown.

**Tech Stack:** Python 3.13, PySide6, pytest, lb_app/lb_gui services.

---

### Task 1: Add GUI UIAdapter + DashboardHandle

**Files:**
- Create: `lb_gui/adapters/__init__.py`
- Create: `lb_gui/adapters/gui_dashboard_handle.py`
- Create: `lb_gui/adapters/gui_ui_adapter.py`
- Test: `tests/unit/lb_gui/test_gui_dashboard_adapter.py`

**Step 1: Write the failing test**

```python
# tests/unit/lb_gui/test_gui_dashboard_adapter.py
import pytest
from lb_controller.services.journal import RunJournal


def test_gui_adapter_initializes_dashboard_via_signal(qtbot):
    from lb_gui.adapters.gui_ui_adapter import GuiUIAdapter
    from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

    plan = [{"name": "dfaas", "intensity": "low"}]
    journal = RunJournal(run_id="run-1", tasks={})
    vm = GUIDashboardViewModel()

    adapter = GuiUIAdapter(vm)
    adapter.create_dashboard(plan, journal, None)

    assert vm.snapshot is not None
    assert vm.snapshot.run_id == "run-1"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_gui/test_gui_dashboard_adapter.py -q`
Expected: FAIL with `ModuleNotFoundError` or missing adapter symbols.

**Step 3: Write minimal implementation**

```python
# lb_gui/adapters/gui_dashboard_handle.py
from __future__ import annotations
from PySide6.QtCore import QObject, Signal
from lb_app.api import DashboardHandle


class GuiDashboardSignals(QObject):
    init_dashboard = Signal(object, object)  # plan, journal
    log_line = Signal(str)
    refresh = Signal()
    warning = Signal(str, float)
    controller_state = Signal(str)


class GuiDashboardHandle(DashboardHandle):
    def __init__(self, signals: GuiDashboardSignals) -> None:
        self._signals = signals

    def live(self):
        from contextlib import nullcontext
        return nullcontext()

    def add_log(self, line: str) -> None:
        self._signals.log_line.emit(line)

    def refresh(self) -> None:
        self._signals.refresh.emit()

    def mark_event(self, source: str) -> None:
        _ = source
        # No-op for GUI

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        self._signals.warning.emit(message, ttl)

    def set_controller_state(self, state: str) -> None:
        self._signals.controller_state.emit(state)
```

```python
# lb_gui/adapters/gui_ui_adapter.py
from __future__ import annotations
from PySide6.QtCore import QObject
from lb_app.api import UIAdapter, ProgressHandle, NoOpProgressHandle
from lb_gui.adapters.gui_dashboard_handle import GuiDashboardHandle, GuiDashboardSignals
from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel


class GuiUIAdapter(QObject, UIAdapter):
    def __init__(self, dashboard_vm: GUIDashboardViewModel) -> None:
        super().__init__()
        self._vm = dashboard_vm
        self._signals = GuiDashboardSignals()
        self._signals.init_dashboard.connect(self._vm.initialize)
        self._signals.log_line.connect(self._vm.on_log_line)
        self._signals.refresh.connect(self._vm.refresh_snapshot)
        self._signals.warning.connect(self._vm.on_warning)
        self._signals.controller_state.connect(self._vm.on_status)

    def show_info(self, message: str) -> None:
        self._vm.on_status(message)

    def show_warning(self, message: str) -> None:
        self._vm.on_warning(message, 10.0)

    def show_error(self, message: str) -> None:
        self._vm.on_status(f"Error: {message}")

    def show_success(self, message: str) -> None:
        self._vm.on_status(message)

    def show_panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None:
        _ = (message, title, border_style)
        self._vm.on_log_line(message)

    def show_rule(self, title: str) -> None:
        self._vm.on_log_line(title)

    def show_table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        _ = (title, columns, rows)

    def status(self, message: str):
        from contextlib import nullcontext
        self._vm.on_status(message)
        return nullcontext()

    def create_progress(self, description: str, total: int) -> ProgressHandle:
        _ = (description, total)
        return NoOpProgressHandle()

    def create_dashboard(self, plan: list[dict[str, object]], journal: object, ui_log_file=None):
        _ = ui_log_file
        self._signals.init_dashboard.emit(plan, journal)
        return GuiDashboardHandle(self._signals)

    def prompt_multipass_scenario(self, options: list[str], default_level: str):
        _ = (options, default_level)
        return None
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_gui/test_gui_dashboard_adapter.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add lb_gui/adapters tests/unit/lb_gui/test_gui_dashboard_adapter.py
git commit -m "feat(gui): add UI adapter dashboard wiring"
```

---

### Task 2: Wire adapter into GUI run flow + real journal

**Files:**
- Modify: `lb_gui/windows/main_window.py`
- Modify: `lb_gui/viewmodels/run_setup_vm.py`
- Test: `tests/unit/lb_gui/test_run_worker.py`

**Step 1: Write the failing test**

```python
# tests/unit/lb_gui/test_run_worker.py
from unittest.mock import patch


def test_run_request_includes_run_id_and_stop_file():
    from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

    vm = RunSetupViewModel(None, None)  # patched in test, or use simple mocks
    # ... set minimal fields to make build_run_request valid ...
    request = vm.build_run_request()
    assert request.run_id
    assert request.stop_file is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_gui/test_run_worker.py -q`
Expected: FAIL (run_id/stop_file missing)

**Step 3: Write minimal implementation**

```python
# lb_gui/viewmodels/run_setup_vm.py
from lb_app.services.run_journal import generate_run_id

run_id = self._run_id or generate_run_id()
stop_file = Path(self._stop_file) if self._stop_file else (self._config.output_dir / run_id / "STOP")

return RunRequest(
    # ...
    run_id=run_id,
    stop_file=stop_file,
)
```

```python
# lb_gui/windows/main_window.py
from lb_gui.adapters.gui_ui_adapter import GuiUIAdapter

# in on_start_run(request):
adapter = GuiUIAdapter(dashboard_vm)
request.ui_adapter = adapter
self._current_stop_file = request.stop_file
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_gui/test_run_worker.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add lb_gui/viewmodels/run_setup_vm.py lb_gui/windows/main_window.py tests/unit/lb_gui/test_run_worker.py
git commit -m "feat(gui): pass adapter and default stop file"
```

---

### Task 3: Sidebar Stop button + confirmation

**Files:**
- Modify: `lb_gui/windows/main_window.py`
- Test: `tests/unit/lb_gui/test_main_window_workflow.py`

**Step 1: Write the failing test**

```python
# tests/unit/lb_gui/test_main_window_workflow.py
from pathlib import Path
from unittest.mock import patch


def test_stop_button_touches_stop_file(qtbot, tmp_path):
    from lb_gui.windows.main_window import MainWindow
    # ... build MainWindow with mocks ...
    win = MainWindow(services_mock)
    win._current_stop_file = tmp_path / "STOP"
    with patch("lb_gui.windows.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        win._on_stop_clicked()
    assert win._current_stop_file.exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_gui/test_main_window_workflow.py -q`
Expected: FAIL (no stop button/handler)

**Step 3: Write minimal implementation**

```python
# lb_gui/windows/main_window.py
from PySide6.QtWidgets import QPushButton
from pathlib import Path

# In _setup_ui():
self._sidebar_container = QWidget()
sidebar_layout = QVBoxLayout(self._sidebar_container)
sidebar_layout.setContentsMargins(0, 0, 0, 0)
sidebar_layout.addWidget(self._sidebar)

self._stop_button = QPushButton("Stop Run")
self._stop_button.setEnabled(False)
self._stop_button.clicked.connect(self._on_stop_clicked)
sidebar_layout.addWidget(self._stop_button)

main_layout.addWidget(self._sidebar_container)

# In _set_ui_busy():
self._sidebar.setEnabled(not busy)
self._stop_button.setEnabled(busy and self._current_worker and self._current_worker.is_running())

# Handler:
def _on_stop_clicked(self):
    if not self._current_stop_file:
        QMessageBox.warning(self, "Stop", "Stop file path not available.")
        return
    reply = QMessageBox.question(...)
    if reply != QMessageBox.StandardButton.Yes:
        return
    Path(self._current_stop_file).parent.mkdir(parents=True, exist_ok=True)
    Path(self._current_stop_file).write_text("stop")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_gui/test_main_window_workflow.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add lb_gui/windows/main_window.py tests/unit/lb_gui/test_main_window_workflow.py
git commit -m "feat(gui): add graceful stop button"
```

---

### Task 4: End-to-end GUI dashboard refresh

**Files:**
- Modify: `lb_gui/viewmodels/dashboard_vm.py`
- Test: `tests/unit/lb_gui/test_dashboard_vm.py`

**Step 1: Write the failing test**

```python
# tests/unit/lb_gui/test_dashboard_vm.py
from lb_controller.services.journal import RunJournal, TaskState


def test_refresh_snapshot_reads_real_journal():
    from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

    journal = RunJournal(run_id="run-1", tasks={})
    journal.add_task(TaskState(host="h", workload="w", repetition=1))
    vm = GUIDashboardViewModel()
    vm.initialize([{"name": "w", "intensity": "low"}], journal)
    vm.refresh_snapshot()

    rows = vm.get_journal_rows()
    assert rows
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_gui/test_dashboard_vm.py -q`
Expected: FAIL if snapshot not updated.

**Step 3: Write minimal implementation**

```python
# lb_gui/viewmodels/dashboard_vm.py
# Ensure refresh_snapshot emits and uses the real journal (already does). If missing, add:
self._snapshot = self._app_vm.snapshot()
self.snapshot_changed.emit(self._snapshot)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_gui/test_dashboard_vm.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add lb_gui/viewmodels/dashboard_vm.py tests/unit/lb_gui/test_dashboard_vm.py
git commit -m "test(gui): verify dashboard refresh"
```

---

## Notes
- Baseline GUI tests currently fail if `PySide6` is not installed. Install `PySide6` or mark tests with `pytest.importorskip("PySide6")` if needed.
