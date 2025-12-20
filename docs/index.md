<div class="hero">
  <div class="hero__content">
    <p class="hero__eyebrow">Benchmark orchestration for Linux nodes</p>
    <h1 class="hero__title">Linux Benchmark Library</h1>
    <p class="hero__subtitle">
      Run repeatable workloads, collect multi-level metrics, and generate reports with
      a clean CLI and stable Python APIs.
    </p>
    <div class="hero__actions">
      <a class="btn btn--primary" href="quickstart.md">Get started</a>
      <a class="btn btn--ghost" href="api.md">API reference</a>
    </div>
  </div>
  <div class="hero__panel">
    <div class="hero__panel-title">Quick run</div>
    <pre>lb config init -i
lb plugin list --enable stress_ng
lb run --remote --run-id demo-run</pre>
    <p class="hero__panel-note">Provisioned runs are available in dev mode: <code>--docker</code> or <code>--multipass</code>.</p>
  </div>
</div>

## Why this exists

<div class="feature-grid">
  <div class="feature-card">
    <h3>Repeatable workloads</h3>
    <p>Standardize load patterns and run them across hosts or provisioned targets.</p>
  </div>
  <div class="feature-card">
    <h3>Layered architecture</h3>
    <p>Runner, controller, app, and UI are cleanly separated to keep coupling low.</p>
  </div>
  <div class="feature-card">
    <h3>Actionable artifacts</h3>
    <p>Raw metrics, journals, reports, and exports are organized per run and host.</p>
  </div>
  <div class="feature-card">
    <h3>Extensible plugins</h3>
    <p>Add new workloads via entry points and a user plugin directory.</p>
  </div>
</div>

## Core layers

| Layer | Responsibility |
| --- | --- |
| `lb_runner` | Execute workloads and collect metrics on a node. |
| `lb_controller` | Orchestrate remote runs via Ansible and manage state. |
| `lb_app` | Stable API for CLIs/UIs and integrations. |
| `lb_ui` | CLI/TUI implementation. |
| `lb_analytics` | Reporting and post-processing. |
| `lb_provisioner` | Docker/Multipass helpers for the CLI. |

## Where to go next

- Read the [Quickstart](quickstart.md) for CLI and Python examples.
- Use the [CLI reference](cli.md) for all commands.
- Browse the [API reference](api.md) for stable modules.
- Check [Diagrams](diagrams.md) for architecture visuals and release artifacts.
