# Runner / Controller / UI Separation Plan

Goal: split responsibilities cleanly so Runner is installable on targets, Controller orchestrates (Ansible, journaling, parsing, analysis), and UI is a client consuming Controller events/state. Keep current behavior; local execution can stay as-is for now.

## Components & Contracts
- Runner (new package): LocalRunner, plugin registry, plugins, events (LB_EVENT schema). Exposes execution of a single repetition/workload; produces stdout LB_EVENT and artifacts.
- Controller (new package): Orchestration, Ansible invoker, RunJournal, LB_EVENT parsing, artifact collection/backfill, optional analysis/formatting (DataHandler kept here for now).
- UI (new package): CLI/TUI consuming Controller APIs/events. No direct Runner dependency.
- Communication: UI <-> Controller <-> Runner. Runner emits LB_EVENT; Controller ingests/updates journal and publishes state; UI subscribes to Controller (stdout parsing for now).

## Packaging Strategy
- Monorepo with multiple uv projects (e.g., `lb-runner`, `lb-controller`, `lb-ui`) or multiple `tool.uv.project` entries. Keep backcompat shim `lb` that wires Controller+UI.
- Entry points: `lb-runner` (optional), `lb-controller` (headless orchestration), `lb` (UI).

## File Mapping (initial)
- Runner pkg: `local_runner.py`, `plugin_system/*`, `plugins/*`, `events.py`, shared utils. DataHandler optional (see below).
- Controller pkg: `controller.py`, `services/run_service.py`, `journal.py`, `ansible/` (playbooks/roles), processing/backfill, LogSink, LB_EVENT parser.
- UI pkg: `ui/` (dashboard, adapters), CLI wrapper.

## Data/Analysis
- Keep `data_handler.py` in Controller for now (centralized post-processing); Runner stays light and just executes.

## Refactor Steps (safe order)
1) Introduce multipackage structure (uv workspace or multiple projects) without moving code yet; decide package names.
2) Move Runner code into runner package; fix imports (Controller/UI depend on runner).
3) Move Controller code (controller.py, services, journal, ansible) into controller package; fix imports.
4) Move UI into its package; create `lb` entrypoint that uses Controller APIs.
5) Update Ansible setup to install the runner package on targets (pip/uv) instead of repo-editable install.
6) Update docs/CLI/CI to install workspace and run tests; keep `lb` shim for backcompat.
7) Functional verification: multipass run, LB_EVENT propagation, RunJournal updates, log stream, analysis.

## Risks / Costs
- Moderate refactor: imports/path changes, ansible install step tweaks. No behavioral rewrite.
- Time: manageable in 2–3 work cycles if done incrementally with tests after each move.

## Notes
- LB_EVENT schema (events.py) is the public contract between Runner and Controller; formalize it.
- Future UI variants can attach to Controller without touching Runner.
