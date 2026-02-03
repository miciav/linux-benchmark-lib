# Issue: Clarify Protocols vs Concrete Bases

**Title:** Refactor: Separate UI protocols from concrete base implementations

**Priority:** Medium
**Component:** lb_ui

**Description:**
`lb_ui/tui/system/protocols.py` mixes Protocols with concrete classes (`Presenter`, `Dashboard`) and default behaviors. Compatibility shims (`presenter_base.py`, `dashboard_base.py`) obscure the source of truth. This makes the API surface unclear and complicates extensibility.

**Detailed Plan:**
1. Split interfaces into a pure protocols module (e.g., `lb_ui/tui/core/protocols.py`) containing only Protocol definitions.
2. Move concrete helper classes to `lb_ui/tui/core/bases.py`:
   - `Presenter` (as a concrete helper built on `PresenterSink`)
   - `DashboardNoOp` or a simple `NullDashboard`
3. Update imports throughout the codebase to reference the new locations.
4. Remove compatibility shims (`presenter_base.py`, `dashboard_base.py`) once all references are updated.
5. Update `lb_ui/tui/__init__.py` exports to point to the new modules.
6. Add a small import-level test to ensure the public API is stable.

**Acceptance Criteria:**
- Protocols are pure interfaces with no behavior.
- Concrete helper classes live in a clearly named module.
- Compatibility shims are removed.
- Public imports remain stable for external callers.

## Notes
- 2026-01-23: Moved protocol definitions to `lb_ui/tui/core/protocols.py` and concrete helpers to `lb_ui/tui/core/bases.py`.
- 2026-01-23: Updated imports across TUI components, flows, and adapters; removed compatibility shims.
- 2026-01-23: Added a public API import test to keep `lb_ui.tui` exports stable.

## Testing
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_tui_public_api.py tests/unit/lb_ui/test_headless_hierarchical_picker.py`
