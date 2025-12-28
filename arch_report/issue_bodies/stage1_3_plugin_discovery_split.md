## Description
Split plugin discovery, registry storage, and installation/packaging logic into separate modules to clarify boundaries.

## Plan
1. Create `lb_plugins/discovery.py` for entrypoint and user-dir discovery.
2. Keep `PluginRegistry` as storage/factory consuming discovery output.
3. Move packaging/installation helpers into `lb_plugins/installer.py`.
4. Update call sites and ensure `lb_plugins.api` exports remain stable.

## Acceptance Criteria
- Discovery and installer logic are isolated from registry storage.
- `lb_plugins.api` stays stable and plugin list flows pass.

## Risk
Medium.

## Evidence
- `lb_plugins/registry.py:56`
- `lb_plugins/api.py:126`
