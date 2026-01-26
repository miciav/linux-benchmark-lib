# Issue: Unify Picker Implementations

**Title:** Refactor: Consolidate picker implementations into a single engine

**Priority:** High
**Component:** lb_ui

**Description:**
The picker stack has multiple parallel implementations (`_PickerApp`, `_TwoLevelPicker`, `_TwoLevelMultiPicker`, and `PowerHierarchicalPicker`) with overlapping logic and different behaviors. This creates asymmetries and makes it hard to add new selection flows. Consolidate into a single picker engine built on `FlatPickerPanel`, with configurable modes (flat, hierarchical, variants, multi-select).

**Detailed Plan:**
1. Design a unified picker controller that supports:
   - Flat list selection (single and multi)
   - Variants per item (single and multi)
   - Hierarchical navigation (tree path + leaf selection)
2. Extract shared rendering logic into reusable helpers (row renderer, preview renderer, variants panel) inside a new `lb_ui/tui/screens/picker_screen.py`.
3. Migrate `PowerPicker` to use the new picker controller for all modes.
4. Migrate `PowerHierarchicalPicker` to use the unified controller (tree mode) and remove the separate `hierarchical_picker.py` implementation.
5. Remove legacy picker implementations (`_PickerApp`, `_TwoLevelPicker`, `_TwoLevelMultiPicker`) once parity is confirmed.
6. Ensure current behavior remains the same for existing flows (workload selection, plugin selection).
7. Add tests (or headless simulation tests) for:
   - Variant selection behavior
   - Multi-select behavior
   - Hierarchical navigation path selection

**Acceptance Criteria:**
- One picker engine powers all TUI selections.
- Behavior parity with current flows is maintained.
- No duplicate picker implementations remain.
- Tests cover at least variant selection and hierarchical navigation.

## Notes
- 2026-01-23: Added unified picker engine in `lb_ui/tui/screens/picker_screen.py` built on `FlatPickerPanel`.
- 2026-01-23: Replaced legacy pickers with `PowerPicker`/`PowerHierarchicalPicker` wrappers that use the unified engine.
- 2026-01-23: Removed duplicated picker implementations and updated tests to exercise selection state and hierarchy navigation.

## Testing
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_picker_crash.py tests/unit/lb_ui/test_picker_preselection.py tests/unit/lb_ui/test_picker_screen.py tests/unit/lb_ui/test_headless_hierarchical_picker.py`
