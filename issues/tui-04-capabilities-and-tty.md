# Issue: Centralize TTY/Capability Checks

**Title:** Refactor: Centralize TTY detection and optional capability flags

**Priority:** Medium
**Component:** lb_ui

**Description:**
TTY checks and optional dependency handling are scattered across flows and picker components (`sys.exit` in flows, `None` returns in pickers). This creates inconsistent behavior and makes headless/CI behavior unpredictable. Centralize capability detection and use it consistently.

**Detailed Plan:**
1. Add `lb_ui/tui/core/capabilities.py` with helpers:
   - `is_tty_available()`
   - `has_fuzzy_search()` (based on rapidfuzz availability)
   - `supports_fullscreen_ui()` if needed
2. Update pickers to rely on the capability helper instead of direct `sys.stdin`/`sys.stdout` checks.
3. Update flows (`lb_ui/flows/*.py`) to avoid `sys.exit` and instead return a controlled error or raise a typed exception that CLI handles uniformly.
4. Make optional dependency handling consistent:
   - Use the capability helper and fall back to non-fuzzy matching when rapidfuzz is unavailable.
5. Add small tests (or headless tests) to validate capability helper behavior.

**Acceptance Criteria:**
- All TTY/capability checks are centralized.
- UI flows no longer call `sys.exit` for TTY issues.
- Optional fuzzy search behavior is consistent across pickers.
- Headless mode behavior is predictable and testable.

## Notes
- 2026-01-23: Added `lb_ui/tui/core/capabilities.py` and wired pickers/flows to use centralized TTY checks.
- 2026-01-23: Replaced `sys.exit` in selection flows with `UIFlowError` and CLI handling.
- 2026-01-23: Made fuzzy-search optional via capabilities helper and updated FlatPickerPanel fallback behavior.
- 2026-01-23: Added capability helper tests.
- 2026-01-23: Removed direct `lb_controller`/`lb_plugins` imports from lb_ui flows and commands.

## Testing
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_capabilities.py tests/unit/lb_ui/test_picker_crash.py tests/unit/lb_ui/test_picker_preselection.py tests/unit/lb_ui/test_picker_screen.py`
