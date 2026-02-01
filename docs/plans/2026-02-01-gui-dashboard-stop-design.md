# GUI Dashboard Progress + Stop (Graceful) Design

**Goal:** Provide live progress updates in the GUI Dashboard and add a sidebar Stop button that gracefully stops a run.

## Current Problem
- GUI initializes the Dashboard with a placeholder `RunJournal` and does not receive updates from the real journal used by the core.
- As a result, the Progress table stays empty during runs.
- GUI lacks a Stop control equivalent to the TUI's double Ctrl+C (graceful stop).

## Proposed Architecture
- Introduce a GUI-specific `UIAdapter` and `DashboardHandle` that connect the core's run pipeline to Qt signals.
- Pass the GUI `UIAdapter` into the `RunRequest` so the core creates a dashboard tied to the real `RunJournal`.
- Use the existing `StopToken` stop-file mechanism for a graceful stop initiated by the GUI.

## Data Flow (Progress)
1. GUI builds a `RunRequest` with a deterministic `run_id` and stop file path.
2. GUI provides `GuiUIAdapter` in `RunRequest.ui_adapter`.
3. Core calls `ui_adapter.create_dashboard(plan, journal, ...)` and receives a `GuiDashboardHandle`.
4. `GuiDashboardHandle.refresh()` triggers `GUIDashboardViewModel.refresh_snapshot()`.
5. Snapshot reads from the real `RunJournal` (updated by `LogSink.emit()`), so Progress rows update live.

## UI Changes
- Sidebar becomes a vertical container: navigation list + Stop button.
- During a run, navigation list is disabled, Stop button remains enabled.
- Stop button requires confirmation (QMessageBox).

## Graceful Stop Behavior
- On confirm, GUI "touches" the stop file path (default: `output_dir/<run_id>/STOP`).
- Core already watches this file via `StopToken.should_stop()`, resulting in graceful teardown and cleanup.

## Error Handling
- If the stop file cannot be written, show a critical dialog and keep the run active.
- If dashboard wiring fails, GUI continues to show log lines (non-blocking).

## Testing
- Unit test: GUI dashboard viewmodel refresh uses real `RunJournal` and updates rows.
- Unit test: GUI dashboard handle triggers `refresh_snapshot()` on refresh.
- Unit test: Stop button writes stop file on confirm (filesystem mocked).
