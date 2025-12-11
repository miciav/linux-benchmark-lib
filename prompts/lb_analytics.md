You are a **senior software architect and software-engineering researcher (PhD-level)**.
You have full access to the code in this workspace.

The project is organized around three main top-level packages:

* **`lb_runner`** — executes workloads, runs plugins, emits low-level data (LB_EVENT, logs, artifacts).
* **`lb_controller`** — orchestrates runs (Ansible, journaling, LB_EVENT parsing, artifact collection), decides *when* and *what* to analyze.
* **`lb_ui`** — CLI/TUI and all user interaction.

We now want to introduce a **new top-level package**:

* **`lb_analytics`** — responsible for transforming raw benchmark/simulation results into **profiles, processed datasets, reports, plots, and images**.

This package must be **independent and cohesive**, not embedded inside `lb_controller`.
The intended high-level dependency direction is:

```text
lb_runner   →   lb_controller   →   lb_analytics
                               ↑
                               │
                     lb_ui uses analytics outputs only via controller
```

Your task is to **analyze, rethink, and reorganize the architecture** to cleanly introduce `lb_analytics` as a dedicated subsystem while improving cohesion, reducing legacy or accidental design, and eliminating structural asymmetries.

---

## Goals

1. **Identify all analytics-related logic** currently scattered across:

   * `lb_runner` (plugins producing summaries, implicit transformations)
   * `lb_controller` (post-processing, data handling, partial analysis)
   * `lb_ui` (any formatting or metrics computation)
   * legacy or ad-hoc modules

2. **Define a clean, principled role** for the new `lb_analytics` package:

   * Input: raw artifacts, LB_EVENT streams, logs, metrics, RunJournal.
   * Output: structured analytical objects (profiles, datasets), reports, and images.
   * Without dependencies on UI, Ansible, or runner internals.

3. **Detect and highlight non-organic code**, legacy fragments, accidental complexity, and asymmetries across the architecture.

4. **Propose a coherent reorganization**, clarifying responsibility boundaries:

   * `lb_runner` → produces raw data
   * `lb_controller` → orchestrates runs, collects data, invokes analytics
   * `lb_analytics` → transforms data
   * `lb_ui` → eventually displays results (but **UI integration is not required now**)

5. **Produce a safe, incremental refactoring plan**, focusing on cohesion, modularity, and clean layering.

---

## What to Analyze

### 1. Current Responsibilities & Data Flow

* Map how raw data flows from runner → controller → any analytics/summary code today.
* Identify:

  * which modules/classes/functions perform data transformation,
  * where responsibilities are mixed (orchestration + analytics, UI + analytics),
  * inconsistencies or asymmetrical paths across plugins or execution modes.

### 2. Cohesion & Separation of Concerns

* For each existing package (`lb_runner`, `lb_controller`, `lb_ui`), evaluate:

  * which parts of analytics currently pollute their responsibilities,
  * which modules contain mixed concerns (e.g. parsing + analysis + reporting).

* Identify legacy or non-organic artifacts that should be consolidated into `lb_analytics`.

### 3. Designing the `lb_analytics` Package

Define the target architecture of the analytics subsystem:

* Internal structure (e.g. `profiles`, `reports`, `plots`, `stats`, `io`).
* Public API:

  * e.g., `AnalyticsEngine`, `ProfileBuilder`, `ReportGenerator`, `PlotService`.
* Allowed dependencies:

  * may depend on DTOs/artifact formats from runner+controller,
  * must **not** depend on UI, Ansible, subprocess logic, or orchestration internals.

Show how `lb_controller` should use it.

### 4. Package-Level Reorganization

* Propose where to move existing analytics logic into the new package.
* Suggest clear, cohesive submodules inside `lb_analytics`.
* Recommend renaming or splitting modules to eliminate asymmetries and legacy patterns.

### 5. Incremental Refactoring Plan

Provide a stepwise plan, e.g.:

1. Create `lb_analytics` skeleton with internal subpackages (profiles/reports/plots).
2. Move analytics-related functions/classes from controller/runner into the new package.
3. Define stable DTOs or inputs (`RunJournal`, parsed artifacts) used by analytics.
4. Update `lb_controller` to call analytics components.
5. Clean up legacy code, remove duplicates, unify data pathways.
6. Validate behavior through tests and example executions.

Each step should explain:

* what changes,
* why it improves cohesion,
* how to ensure correctness.

---

## Requirements

* All analysis must be in **English**.
* Focus on **architecture, cohesion, and principled design**, not on rewriting everything.
* Avoid UI redesign for now — analytics is *purely backend* at this stage.
