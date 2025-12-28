## Description
Separate system-info dataclasses from collection logic to reduce complexity and improve testability.

## Plan
1. Move `_collect_*` functions and `collect_system_info()` into a collector module.
2. Keep dataclasses (`SystemInfo`, `DiskInfo`, etc.) in a types module.
3. Update call sites and ensure outputs match existing serialization tests.

## Acceptance Criteria
- System-info logic is split between types and collectors.
- Output shape remains unchanged and tests pass.

## Risk
Low.

## Evidence
- `lb_runner/services/system_info.py:186`
- `lb_runner/services/system_info.py:446`
