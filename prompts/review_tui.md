You are a **senior software architect and UI design expert (PhD-level in software engineering)**.
You have full access to the project code in this workspace.

Your task is to **analyze the entire TUI layer of the project** with the goal of identifying:

* structural inconsistencies and asymmetries
* legacy or obsolete patterns
* non-organic or accidental design decisions
* duplicated or scattered UI logic
* unclear separation of concerns
* components that violate principles such as single responsibility, modularity, or consistency

and then propose a **coherent, principle-driven reorganization** of the UI architecture.

---

## What to Analyze

When inspecting the TUI package, please focus on:

### 1. Architectural Cohesion & Separation of Concerns

* Do UI components have clear boundaries?
* Is presentation logic mixed with orchestration or business logic?
* Are there widgets/screens/classes that contain too many unrelated responsibilities?

### 2. Design Consistency & Symmetry

* Are naming conventions, layout patterns, navigation flows, and event-handling strategies consistent across the TUI?
* Are similar features implemented differently (asymmetry)?
* Are some components modern and others legacy-like?

### 3. Code Organicity & Legacy

* Identify parts of the UI that feel:

  * outdated
  * ad-hoc
  * vestiges of earlier architecture
  * patchwork or copy-pasted
* Point out modules that no longer fit the project's evolution.

### 4. Reusability & Extensibility

* Evaluate if components are reusable or tightly coupled.
* Does the current architecture support adding new screens/widgets cleanly?
* Are state and events managed in a scalable, principled way?

### 5. Overall Structural Issues

* Any UI code that depends directly on low-level layers (runner, filesystem, subprocess, ansible, etc.)
* Any implicit dependencies, hidden flows or hardcoded assumptions
* Any “god views” or oversized classes
* Fragmented logic spread across unrelated modules

---

## What to Produce

Please provide a **structured, high-level architectural review** containing:

### 1. Summary of the Current State

A clear description of what the TUI is doing well and what seems inconsistent, accidental, or legacy.

### 2. Identified Issues

A categorized list of:

* structural issues
* non-organic patterns
* asymmetries
* legacy artifacts
* violations of separation of concerns

with specific examples.

### 3. Proposed Redesign Principles

Define a coherent design direction:

* layering (UI → controller → backend)
* component responsibilities
* event/state management
* naming and structural conventions
* guidelines for future extension

### 4. Suggested New Architecture

Propose a clean, modern structure for the TUI package:

* new or reorganized modules
* extraction of responsibilities
* consolidation of duplicated logic
* improved navigation/layout patterns
* optional introduction of a UI state model or event bus

### 5. Incremental Refactoring Plan

Provide a step-by-step roadmap to evolve the current TUI into the proposed architecture **without breaking functionality**, including:

* what to move
* what to split
* what to remove
* what to unify
* how to test the transition

---

## Requirements

* Keep the analysis and proposals **general, conceptual, and architecture-focused**.
* Produce reasoning in **English**.
* Avoid rewriting UI components from scratch; focus on structural improvement, cohesion, symmetry, and adherence to principles such as SRP, modularity, and maintainability.