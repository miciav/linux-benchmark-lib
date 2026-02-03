# Issue: Centralize TUI Theme and Styling

**Title:** Refactor: Create a shared TUI theme for Rich and prompt_toolkit

**Priority:** Low
**Component:** lb_ui

**Description:**
Styles and colors are hardcoded in multiple components (picker, hierarchical picker, dashboard, tables). This creates inconsistencies and makes the UI hard to retheme. Introduce a single theme module that provides style tokens and shared palettes.

**Detailed Plan:**
1. Add `lb_ui/tui/core/theme.py` with:
   - Rich style tokens (color names or hex values)
   - prompt_toolkit style dicts
   - shared constants for separators, headers, and status colors
2. Update all TUI components to reference the theme instead of inline style strings.
3. Ensure any existing custom styling stays visually equivalent (or document changes).
4. Add a small unit test to verify the theme module exports expected keys.

**Acceptance Criteria:**
- No hardcoded style dicts remain in TUI components.
- Theme values are centralized in a single module.
- UI appearance remains consistent across components.

## Notes
- 2026-01-23: Added `lb_ui/tui/core/theme.py` and wired dashboard, presenter, tables, and picker styles to use it.
- 2026-01-23: Centralized status colors, panel titles, and prompt_toolkit style dicts.
- 2026-01-23: Added unit coverage for theme exports.

## Testing
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_tui_theme.py tests/unit/lb_ui/test_picker_screen.py tests/unit/lb_ui/test_adapters_dashboard.py`
