# Plugin Asset Decoupling Plan

Goal: decouple workload plugins from Ansible-specific APIs and let each plugin declare generic assets/steps that runners (local, container, remote) can translate into their own execution model.

## Current pain
- `WorkloadPlugin` exposes `get_ansible_setup_path`/`get_ansible_teardown_path`, coupling plugins to Ansible.
- Local/Container runners ignore setup/teardown entirely; only the Ansible path is exercised.
- Adding new backends (e.g., Kubernetes) or running setup locally is awkward because the contract is tied to playbooks.

## Design direction
- Introduce a backend-agnostic asset model and a single entrypoint: `get_assets() -> WorkloadAssets`.
- Keep legacy methods as a fallback shim during migration to avoid breaking existing plugins/tests.
- Add adapters per runner to translate assets into actionable steps (local commands, container exec, Ansible tasks).

## Proposed data model
- `WorkloadAssets` (dataclass)
  - `setup_steps: list[AssetStep]`
  - `run_steps: list[AssetStep]` (optional; initially unused if runner owns execution loop)
  - `teardown_steps: list[AssetStep]`
- `AssetStep` tagged variants (all optional fields are nullable):
  - `CommandAsset(cmd: list[str], env: dict | None, workdir: Path | None)`
  - `ScriptAsset(path: Path, interpreter: str | None, env: dict | None)`
  - `FileAsset(source: Path, target: Path, executable: bool)`
  - `AnsiblePlaybookAsset(path: Path, tags: list[str] | None)` (for declarative compatibility; still allowed but not the only path)

## Phased plan
1) **API & fallback**
   - Extend `WorkloadPlugin` with `get_assets()`.
   - Implement legacy shim: if `get_assets` is missing, build `WorkloadAssets` from `get_ansible_*` outputs.
   - Add deprecation warning (log) when legacy paths are used.
   - Ship dataclasses and typing only; no behavior change yet.

2) **Adapters per runner**
   - LocalRunner: `LocalAssetExecutor` to run `CommandAsset`/`ScriptAsset`; ignore or warn on `AnsiblePlaybookAsset` unless an optional local-ansible shim is enabled.
   - Container runner: same executor but inside container; `FileAsset` handled via bind/copy.
   - Remote/Ansible: `AnsibleAssetTranslator` to convert assets into playbook snippets or include provided playbooks; support `FileAsset` via copy/module tasks.

3) **Controller integration**
   - BenchmarkController uses `plugin.get_assets()` and feeds steps through the Ansible translator for setup/run/teardown.
   - Preserve current phase semantics (setup/run/collect/teardown) while assets backfill the setup/teardown parts.
   - Keep journal/error wiring intact.

4) **Plugin migration**
   - Update built-in plugins (`stress_ng`, `dd`, `fio`, etc.) to implement `get_assets()` returning `AnsiblePlaybookAsset` initially (minimal diff).
   - Clean up tests/fixtures that monkeypatch `get_ansible_setup_path` to use `get_assets` or the shim.

5) **Testing**
   - Unit: asset-to-ansible translation, local execution of Command/Script, legacy shim coverage.
   - Integration: one happy-path remote run using new assets; ensure Multipass tests still pass with staged keys.

6) **Deprecation & docs**
   - Document the new asset API in `PLUGIN_DEVELOPMENT.md`.
   - Emit warnings for legacy methods; set a future removal version/timeline.
   - Note behavior changes: setup/teardown now available for local/container runs when assets are provided.

## Milestones / PR slices
1. Add dataclasses (`WorkloadAssets`, `AssetStep` variants) + plugin shim + warnings (no behavior change).
2. Add adapters (Local/Container/Ansible translators) with unit tests.
3. Wire BenchmarkController/LocalRunner to consume assets; keep legacy compatibility path.
4. Migrate built-in plugins; fix tests/fixtures; update docs and changelog.
5. Remove legacy APIs: drop `get_ansible_*` from interface, delete shim, and fail fast if legacy methods are used (final cleanup once all plugins/tests are migrated).

## Risks & mitigations
- **Regression for existing plugins**: mitigated via shim + warnings; ensure registry uses fallback when `get_assets` is absent.
- **Adapter complexity in controller**: keep the asset alphabet small; cache generated temp playbooks per run.
- **Test churn**: update monkeypatch sites early; add unit tests to lock behavior before integration refactors.
