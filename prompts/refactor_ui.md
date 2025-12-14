You are a senior software engineer and software architect with deep expertise in Python CLIs, terminal UI systems, and clean architecture. Your task is to **refactor and reorganize the user interaction layer** of an existing Python project so that it becomes **coherent, reusable, testable, and strictly aligned with software engineering principles**.

This prompt is **self-contained**. All required reference implementations are included below.
You must **reuse, adapt, and encapsulate** them as instructed.

---

## 🎯 Core Objective

Design and enforce a **terminal UI design system** where:

1. **All tabular output** uses a **single reusable Table component**, based on the Rich tables already used in the project.
2. **All interactive selection** uses a **single powerful selector component**, explicitly based on the **Power Picker reference implementation provided below**.
3. **Complex live status** uses a **single reusable Dashboard component** for visualizing run progress and logs.
4. UI logic is **never scattered** across CLI commands, services, or helper functions.

---

## 🧠 Absolute Engineering Principles (Non-Negotiable)

Apply these rigorously:

### 1. Separation of Concerns

* Services / use-cases return **data**, not formatted output.
* UI layer renders data and collects user input.
* CLI commands orchestrate flow only.

### 2. Single Responsibility Principle (SRP)

* Table component → tables only
* Picker component → selection only
* Dashboard component → live progress & logs
* Presenter → generic rendering (messages, panels, previews)

### 3. Dependency Inversion Principle (DIP)

* CLI code depends on **UI interfaces**, not Rich, Typer, or prompt_toolkit.
* UI libraries are implementation details hidden behind adapters.

### 4. Consistency by Construction

* If the application shows a table → it MUST use the Table component
* If the application selects something → it MUST use the Power Picker
  There must be no alternative paths.

---

## 🚫 HARD BANS (Strict)

Outside the UI layer (commands, services, use-cases):

* ❌ No `rich.print`, `Console()`, `Panel`, `Table`
* ❌ No `typer.echo`, `print`
* ❌ No `prompt_toolkit`, `InquirerPy`, `questionary`
* ❌ No ad-hoc `prompt_*` or `select_*` helpers
* ❌ No duplicated rendering logic

All interaction MUST go through the UI facade.

---

## 🧩 UI Facade (Single Entry Point)

```python
class UI(Protocol):
    picker: Picker
    tables: TablePresenter
    present: Presenter
    form: Form
    progress: Progress
    dashboard: DashboardFactory
```

CLI commands receive a `UI` instance and use **only** these components.

---

## 📊 TABLES — Reuse Existing Logic, Encapsulate It

### Important Clarification

* Existing Rich tables in the project are **conceptually correct**
* BUT:

  * They must NOT be created inline
  * They must be encapsulated into a reusable component

### Required Abstraction

```python
@dataclass
class TableModel:
    title: str
    columns: list[str]
    rows: list[list[str]]
```

```python
class TablePresenter(Protocol):
    def show(self, table: TableModel) -> None: ...
```

Implementation:

* `RichTablePresenter` converts `TableModel` → Rich `Table`
* Commands only construct `TableModel`, never Rich objects

❌ Inline `Table(...)` usage outside UI is forbidden.

---

## 🔎 SELECTION — Mandatory Power Picker Component

### This Is Non-Negotiable

All interactive selection MUST be implemented using a **Power Picker component derived from the reference implementation below**.

This component must:

* use `prompt_toolkit` for layout and key handling
* use `rapidfuzz` for fuzzy search
* use `rich` for preview rendering
* support large lists (≥1000 items)
* be reusable everywhere

---

## 📦 Picker Data Model

```python
@dataclass(frozen=True)
class PickItem:
    id: str
    title: str
    tags: tuple[str, ...] = ()
    description: str = ""
    search_blob: str = ""
    preview: object | None = None  # Rich renderable
    payload: Any = None            # domain object
```

---

## 🔌 Picker Interface

```python
class Picker(Protocol):
    def pick_one(
        self,
        items: Sequence[PickItem],
        *,
        title: str,
        query_hint: str = ""
    ) -> PickItem | None

    def pick_many(
        self,
        items: Sequence[PickItem],
        *,
        title: str,
        query_hint: str = ""
    ) -> list[PickItem]
```

---

## 📈 DASHBOARD — Reusable Live Component

### Requirement

For long-running tasks (like benchmarks), the application must provide a live dashboard that displays:
1. A summary table of workloads and their status.
2. A scrolling log stream panel.

### Interface

```python
class Dashboard(Protocol):
    def live(self) -> ContextManager[None]: ...
    def add_log(self, line: str) -> None: ...
    def refresh(self) -> None: ...
    def mark_event(self, source: str) -> None: ...

class DashboardFactory(Protocol):
    def create(self, plan: list[Any], journal: Any) -> Dashboard: ...
```

---

## 🧪 Testing Requirement — Headless UI

Provide a `HeadlessUI` implementation that:

* never imports Rich or prompt_toolkit
* returns deterministic selections
* records tables/messages/logs for assertions
* provides a stub implementation for the Dashboard

---

## ✅ Acceptance Criteria

The refactor is complete only if:

* All tables go through the reusable Table component
* All selections go through the Power Picker
* No Rich / prompt_toolkit imports exist outside UI
* No duplicated rendering logic exists
* A Headless UI exists and is usable in tests
* Architecture clearly reflects SRP, DIP, and clean layering

---

## 🚀 Final Instruction

Do not take shortcuts.
Do not reintroduce ad-hoc helpers.
Prefer **few high-level components reused everywhere** over many utilities.

Design and implement a **professional-grade terminal UI architecture**.
