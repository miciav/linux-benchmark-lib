# Loki + Grafana Requirements

This document captures the agreed requirements for Loki/Grafana integration.

## Scope

- Centralized system logs for all components (runner, generator, k6, etc.) via Loki.
- Optional Grafana integration via the observability provisioning flow.
- Preserve the existing synchronous controller API, while keeping the async API
  available for advanced integrations.

## Decisions (confirmed)

- Loki is optional. When configured, components push logs directly to Loki.
- Logs are always written to local files (JSONL) on the node that produces them.
- During teardown/collect, local logs are copied to the controller node.
- Loki runs on the controller node, not on targets.
- Loki and Grafana are self-hosted.
- Grafana is an optional observability dependency; plugins supply assets (datasources + dashboards).
- Provide an install script that asks the user how to install Loki
  (brew, apt, docker) and performs the install. Provide an uninstall script.
- Supported OS targets for the install script: macOS and Ubuntu 24.04+.
- Grafana should ship with a default dashboard for the dfaas plugin.

## Functional Requirements

### Logging + Loki

- All components (runner, generator, k6, etc.) must be able to push logs to Loki.
- k6 must support direct Loki output when configured (e.g. via k6 `--out`).
- Loki push is optional and should be enabled only when configured.
- Loki push must not block execution; on failure it should fall back to file-only.

### Local Log Fallback (always on)

- Every component writes logs locally, always.
- Standard log format: JSONL with a consistent schema:
  - timestamp, level, component, host, run_id, logger, message, event_type
  - workload, repetition (always present)
  - optional: scenario, tags
- Repetition values are 1-based.
- Tags should include a phase label for install/setup/teardown when applicable.

### Log Collection to Controller

- During teardown/collect, local logs are copied to the controller node.
- Collection should be best-effort even on abort/stop.
- Log naming must avoid collisions:
  - example: benchmark_results/<run_id>/logs/<component>-<host>.jsonl

### Loki Installation

- Provide a script that asks the user to choose installation method:
  - brew (macOS)
  - apt (Ubuntu 24.04+)
  - docker (macOS/Linux)
- Provide a matching uninstall script that cleans up the chosen install.

### Grafana (observability provisioning)

- Grafana is configured via `lb provision loki-grafana` (global provisioning).
- Plugins that use Grafana must expose:
  - datasource definitions (e.g., Prometheus URL from plugin config)
  - dashboard JSON assets

### Async API Preservation

- Primary controller API remains synchronous.
- Async helpers remain available for advanced integrations:
  - keep `lb_controller.async_api` and document its optional usage.

## Non-Functional Requirements

- Compatibility: existing flows must work without Loki/Grafana configured.
- Resilience: Loki failures do not break runs; file logs remain authoritative.
- Performance: logging should be low-overhead, especially in high-volume phases.

## Configuration Requirements

- Provide a clear configuration surface (file/env/CLI) for:
  - Loki endpoint and labels
  - Grafana endpoint and credentials
  - Prometheus endpoint (dfaas)
  - enable/disable flags for Loki and Grafana

## Labels and Metadata (Loki)

- Minimum required labels: component, host, run_id, workload, repetition.
- Recommended labels: scenario.

## Open Questions / TBD

- Auth/TLS for Loki, Prometheus, Grafana (basic auth, token, TLS settings).
- Log retention/rotation and optional compression at collection time.
- Retry policy for Loki push (backoff, max retries).
