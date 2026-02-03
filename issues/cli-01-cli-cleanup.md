# Issue: CLI Command Cleanup and Consistency

**Title:** Refactor: Clean up CLI command surface and inconsistencies

**Priority:** Medium
**Component:** lb_ui

**Description:**
The CLI has grown inconsistent across commands (duplicate resume flows, mixed option names, interactive prompts in headless contexts, and plugin management side effects). Clean up the command surface to be explicit, consistent, and easy to maintain.

**Detailed Plan:**
1. Remove duplicate resume handling from `lb run`; keep `lb resume` as the sole resume entrypoint.
2. Move `analyze` under `lb runs analyze` to keep run inspection commands grouped.
3. Standardize config flags (`--config/-c`) for config init/edit and reduce option naming drift.
4. Make plugin commands explicit (`list`, `enable`, `disable`, `select`), removing list side effects and compatibility aliases.
5. Fix `lb_ui` imports to use only `lb_app.api`/`lb_common.api`.
6. Align docs and CLI tests with the cleaned surface.

**Acceptance Criteria:**
- `lb run` no longer accepts `--resume`.
- `lb runs analyze` is the only analyze entrypoint.
- Config commands consistently accept `--config/-c` for file paths.
- Plugin management uses explicit subcommands with no side effects in `list`.
- `lb_ui` does not import from `lb_app.services` or other non-API modules.
- CLI docs and tests reflect the updated behavior.

## Notes
- 2026-01-23: Issue created.
- 2026-01-23: Removed `--resume` from `lb run` and aligned resume with shared helpers + notifications.
- 2026-01-23: Moved analytics under `lb runs analyze` and added headless guard for run selection.
- 2026-01-23: Standardized config init/edit to `--config/-c`.
- 2026-01-23: Reworked plugin commands into explicit list/enable/disable/select flow.
- 2026-01-23: Exposed `results_exist_for_run` in `lb_app.api` to keep `lb_ui` on stable API.
- 2026-01-23: Updated external docs (README + docs/*) to reflect CLI changes.

## Testing
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_cli.py tests/unit/lb_ui/test_cli_runs_analyze.py`
