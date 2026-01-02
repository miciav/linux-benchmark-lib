# DFaaS Plugin Quality & Refactoring Epic

## Objective
Improve code quality, maintainability, and robustness of the DFaaS plugin implementation through systematic refactoring and stabilization.

## Background
Analysis of the `feature/runner-controller-ui` branch identified several issues:
- 2 failing unit tests
- Monolithic generator class (966 lines)
- Broad exception handling (15+ `except Exception` with `noqa: BLE001`)
- Hardcoded configuration values
- Incomplete documentation
- Fragile E2E test patterns

## Scope
- Fix all identified issues in DFaaS plugin
- Decompose `DfaasGenerator` into smaller, testable components
- Improve error handling with specific exception types
- Complete documentation
- Improve test resilience

## Out of scope
- Core library changes
- New DFaaS features
- Performance optimization

## Milestones

### Milestone 1: Stabilization (P0)
Fix critical issues blocking CI and documentation.
- DFAAS-FIX-1: Fix failing unit tests
- DFAAS-FIX-2: Complete README documentation

### Milestone 2: Architecture (P1)
Decompose monolithic generator into maintainable components.
- DFAAS-REFACTOR-1: Extract K6Runner service
- DFAAS-REFACTOR-2: Extract CooldownManager
- DFAAS-REFACTOR-3: Extract MetricsCollector
- DFAAS-REFACTOR-4: Decompose _run_command()

### Milestone 3: Quality (P2)
Improve error handling, configurability, and test resilience.
- DFAAS-QUALITY-1: Improve error handling
- DFAAS-QUALITY-2: Fix polling limit hardcoded
- DFAAS-QUALITY-3: Configurable ports
- DFAAS-QUALITY-4: Reduce env var coupling
- DFAAS-QUALITY-5: Improve E2E test resilience

## Linked Issues
- #XX DFAAS-FIX-1: Fix failing unit tests
- #XX DFAAS-FIX-2: Complete README documentation
- #XX DFAAS-REFACTOR-1: Extract K6Runner service
- #XX DFAAS-REFACTOR-2: Extract CooldownManager
- #XX DFAAS-REFACTOR-3: Extract MetricsCollector
- #XX DFAAS-REFACTOR-4: Decompose _run_command()
- #XX DFAAS-QUALITY-1: Improve error handling
- #XX DFAAS-QUALITY-2: Fix polling limit hardcoded
- #XX DFAAS-QUALITY-3: Configurable ports
- #XX DFAAS-QUALITY-4: Reduce env var coupling
- #XX DFAAS-QUALITY-5: Improve E2E test resilience

## Dependency Graph
```
011 (fix tests) ──► 012 (complete readme)
                         │
                         ▼
              ┌──────────┴──────────┐
              ▼                     ▼
         013 (k6 runner)      018 (polling)
              │
              ▼
         014 (cooldown)
              │
              ▼
         015 (metrics)
              │
              ▼
         016 (decompose) ──► 017 (errors) ──► 020 (env vars)

019 (ports) - independent
021 (e2e) - independent
```

## Estimated Effort
| Milestone | Issues | Effort |
|-----------|--------|--------|
| P0 Stabilization | 2 | 3h |
| P1 Architecture | 4 | 14h |
| P2 Quality | 5 | 12h |
| **Total** | **11** | **29h** |

## Acceptance Criteria
- [ ] All 17 DFaaS unit tests pass
- [ ] `generator.py` reduced from 966 to ~400 lines
- [ ] No `noqa: BLE001` suppressions remaining
- [ ] README has all required sections (Architecture, Prerequisites, Setup, Run flow, Outputs, Troubleshooting)
- [ ] E2E tests have explicit skip reasons logged
- [ ] All new code has corresponding unit tests

## Success Metrics
- Unit test pass rate: 100%
- Code coverage for DFaaS plugin: >80%
- Cyclomatic complexity per method: <10
- Max file length: <500 lines

