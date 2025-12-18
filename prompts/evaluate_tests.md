### Prompt: Test Suite Analysis and Evaluation

You are a **senior software engineer and testing/QA expert (PhD level)**.
You have full access to the codebase *and* all tests in this workspace.

The project is organized into these top-level packages:

* `lb_runner` – execution, plugins, emission of raw metrics/events and artifacts.
* `lb_controller` – orchestration (Ansible, journaling, LB_EVENT parsing, artifact collection).
* `lb_ui` – CLI/TUI and user interaction.
* `lb_provisioner` - provisioning remote nodes.
* `lb_analytics` – analytics layer for transforming raw data into profiles, reports, and images.

Your task is to **analyze and evaluate the existing test suite**, with a focus on:

* How well the tests cover the responsibilities of these packages
* Test design quality (clarity, isolation, robustness)
* Alignment between tests and the intended architecture/layers
* Gaps, risks, and concrete improvement suggestions

You should focus on **reasoning and assessment**, not just generating new tests blindly.

---

## What to do

### 1. Test Inventory and Mapping

1. Inspect the test structure (e.g. `tests/`, `tests/unit`, `tests/integration`, etc.).
2. For each top-level package (`lb_runner`, `lb_controller`, `lb_ui`, `lb_provisioner` `lb_analytics`), identify:

   * Which test files and test classes/functions target it.
   * Which main behaviors or components they exercise.

Summarize the mapping: *“these tests cover these parts of the system.”*

---

### 2. Coverage of Responsibilities

For each package, evaluate whether **core responsibilities** are reasonably covered:

* **`lb_runner`**

  * Are plugins and execution paths tested?
  * Are error/edge cases (bad config, failures, timeouts) covered?
  * Is LB_EVENT emission tested with realistic inputs?

* **`lb_controller`**

  * Are orchestration flows tested (local, Docker, remote/multipass where applicable)?
  * Is LB_EVENT parsing → RunJournal update tested?
  * Are interactions with external tools (Ansible, subprocesses) tested via mocks/fakes or integration tests?

* **`lb_ui`**

  * Are CLI commands tested (arguments, help, error messages, wiring to controller)?
  * If TUI exists, are there at least some tests around UI logic/state (even if not visual layout)?

* **`lb_analytics`** (if present or partially implemented)

  * Are data transformations, profile building, and report/plot generation tested?
  * Are tests deterministic and independent from external state (no random flakiness)?

  * **`lb_provisioner`** (if present or partially implemented)

  * Are provisioning flows tested (local, Docker, remote/multipass where applicable)?

Call out **which responsibilities are well covered** and **which are barely or not covered**.

---

### 3. Test Quality and Design

Evaluate test quality along these dimensions:

* **Clarity and intent**

  * Are test names descriptive (what behavior is being verified)?
  * Is the Arrange–Act–Assert structure clear?

* **Isolation and determinism**

  * Do tests avoid unnecessary dependencies on network, real time, external tools, or global state?
  * Are there any flaky/timing-sensitive tests?

* **Use of fixtures and helpers**

  * Are pytest fixtures used appropriately (for configs, journals, temp dirs, fake runners, etc.)?
  * Are fixtures small and composable, or too magical and opaque?

* **Structure and maintainability**

  * Are tests organized in a way that mirrors the production code structure (per package/module)?
  * Are there “god tests” that try to do too much in one go?

Highlight concrete examples of **good** tests and **problematic** tests.

---

### 4. Alignment with Architecture and Layers

Check whether the tests respect the intended layering:

```text
lb_runner   ←   lb_controller   ←   lb_ui    
             lb_analytics ←   lb_ui
             lb_provisioner ←   lb_ui
```

Identify any misalignments, such as:

* UI tests that talk directly to `lb_runner` instead of going through `lb_controller`.
* Controller tests that depend too deeply on UI details.
* Analytics tests (if any) that are coupled to orchestration or UI concerns instead of pure data inputs/outputs.

Explain how well the tests reinforce the architecture versus undermining it.

---

### 5. Gaps, Risks, and Missing Tests

Identify **gaps** in the test suite, especially where:

* Behavior is complex or critical but scarcely tested (e.g. `lb run --multipass` flows, error handling across nodes).
* New architectural pieces (journaling, analytics pipeline, event streaming) have little or no direct tests.
* Refactoring would be risky due to lack of coverage.

Produce a **prioritized list of high-risk areas** where missing or weak tests are particularly dangerous.

---

### 6. Recommendations and Improvement Plan

Provide **actionable recommendations**, including:

1. **Short-term improvements**

   * Specific unit tests that should be added first (e.g., LB_EVENT parsing, analytics core functions).
   * Integration tests that would significantly increase confidence for key flows.
   * Simple refactorings of existing tests to make them clearer or less fragile.

2. **Medium-term improvements**

   * Reorganizing tests to better match package structure (`tests/lb_runner`, `tests/lb_controller`, etc.).
   * Refactoring to use markers.
   * Creating shared fixtures/utilities for common patterns (e.g., fake RunJournal, fake Ansible runner).

3. **Principles/Guidelines**

   * High-level testing guidelines specific to this project (what to mock, where to put new tests, how to test new plugins/analytics features).

---

## Output format

Your output should be a **structured, English-language report** with sections:

1. Overall Test Suite Overview
2. Per-Package Evaluation (`lb_runner`, `lb_controller`, `lb_ui`, `lb_analytics`, `lb_provisioner`)
3. Test Quality & Architectural Alignment
4. Gaps and High-Risk Areas
5. Recommendations & Step-by-Step Improvement Plan

Think and reason as a testing/architecture expert reviewing the project to judge how safe it is to evolve and refactor.