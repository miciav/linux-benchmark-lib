## Description
Split `LocalRunner` orchestration into helper components to reduce multi-concern complexity without changing public APIs.

## Plan
1. Extract run planning and output directory setup into a helper under `lb_runner/engine`.
2. Extract collector lifecycle into a `CollectorCoordinator` under `lb_runner/services`.
3. Extract results persistence into a `ResultPersister` helper.
4. Keep `LocalRunner` as the orchestrator that delegates to helpers.

## Acceptance Criteria
- `LocalRunner` delegates to helpers and is materially smaller.
- Public API in `lb_runner.api` remains unchanged.
- Unit tests from Stage 0 remain green.

## Risk
Medium. Core execution flow touched.

## Evidence
- `lb_runner/engine/runner.py:59`
- `lb_runner/engine/runner.py:136`
