## Description
Epic for Stage 1 work: low-risk structural refactors to reduce multi-concern objects without changing public APIs.

## Scope
- Split LocalRunner orchestration helpers.
- Split AnsibleRunnerExecutor helpers.
- Separate plugin discovery/installer logic.
- Split system-info collectors from types.

## Linked Issues
- [ ] #36 Stage 1.1 - Split LocalRunner orchestration
- [ ] #37 Stage 1.2 - Split AnsibleRunnerExecutor helpers
- [ ] #38 Stage 1.3 - Split plugin discovery and installer
- [ ] #39 Stage 1.4 - Split system-info collectors from types

## Exit Criteria
- Public APIs remain stable.
- Targeted unit tests green.
- Reduced size/complexity in targeted modules.
