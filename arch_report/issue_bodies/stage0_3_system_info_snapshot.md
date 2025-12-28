## Description
Add snapshot tests for system-info serialization to lock down output shape used by analytics and reporting.

## Plan
1. Add tests for `SystemInfo.to_dict()` with minimal, deterministic data.
2. Add tests for `SystemInfo.to_csv_rows()` to assert key sections and row counts.
3. Ensure tests do not depend on actual host commands.

## Acceptance Criteria
- Unit tests validate schema stability for `SystemInfo` outputs.
- Tests pass in CI without system tooling.

## Risk
Low.

## Evidence
- `lb_runner/services/system_info.py:129`
- `lb_runner/services/system_info.py:148`
