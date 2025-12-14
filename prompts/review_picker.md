## Role and Mindset

You are a **senior software engineer and architect** with strong expertise in:

* Python CLIs
* Terminal UI design
* prompt_toolkit
* Rich
* Clean Architecture and SOLID principles

You are tasked with designing and implementing a **hierarchical, multi-level selection component** for a professional CLI application.

This is not a toy UI.
It is a **core architectural component** that must be reused everywhere interactive selection occurs.

---

## 🎯 Objective

Design and implement a **Hierarchical Picker** that:

1. Allows users to **navigate a multi-level selection tree**
2. Clearly expresses **domain hierarchy**
3. Supports **progressive refinement**
4. Provides **context-aware preview**
5. Is reusable, testable, and cleanly architected

The picker must be implemented using:

* `prompt_toolkit` for layout, focus, and key handling
* `rich` for preview rendering
* optional fuzzy filtering at the **current level only**

---

## 🧠 Core Design Principles (Non-Negotiable)

Apply these strictly:

### 1. Separation of Concerns

* Navigation state ≠ rendering
* Rendering ≠ domain logic
* CLI commands ≠ UI implementation

### 2. Single Responsibility Principle (SRP)

* One component manages navigation state
* One component renders the current level
* Preview rendering is pluggable

### 3. Dependency Inversion Principle (DIP)

* CLI depends on picker interface
* picker implementation hides prompt_toolkit / Rich

### 4. Domain Expressiveness

The picker must reflect:

* hierarchy
* relationships
* decision flow

Flat lists are insufficient.

---

## 🧩 Data Model (MANDATORY)

### Selection Node

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class SelectionNode:
    id: str
    label: str
    kind: str                      # e.g. "category", "plugin", "profile", "option"
    children: list["SelectionNode"] = field(default_factory=list)
    payload: Any | None = None     # domain object
    preview: object | None = None  # Rich renderable (optional)
```

This model is:

* domain-agnostic
* hierarchical
* UI-friendly

---

## 🧭 Picker State (Explicit and Testable)

```python
@dataclass
class PickerState:
    path: list[SelectionNode]      # breadcrumb
    current: SelectionNode         # active node
    filter: str = ""
```

All navigation must operate by **transforming this state**.

---

## 🔌 Public Interface (What CLI Uses)

```python
class HierarchicalPicker(Protocol):
    def pick_one(
        self,
        root: SelectionNode,
        *,
        title: str
    ) -> SelectionNode | None
```

* The input is a **root node**
* The output is a **selected leaf node** (or `None` on cancel)
* CLI code must never see prompt_toolkit or Rich

---

## 🎛 UX & Interaction Model (MANDATORY)

### Layout (Conceptual)

```
┌────────────────────────────────────────────────────────────┐
│ <TITLE>                                                    │
│ Path: Plugins > CPU                                       │
│ Search: fio                                               │
│                                                           │
│  ▸ fio            Flexible IO Tester                      │
│    dd             Raw disk test                           │
│                                                           │
│ ───────────────────────────────────────────────────────── │
│ Preview                                                   │
│ fio                                                       │
│ Category: IO                                              │
│ Highly configurable disk benchmark                        │
└────────────────────────────────────────────────────────────┘
```

### Keybindings

* `Enter` → descend into node OR select leaf
* `Backspace` / `←` → go up one level
* `Esc` → cancel
* `Up / Down` → navigate
* `Ctrl+R` → reset filter
* Typing → filters **only current level**

---

## 🧠 Architectural Requirement

The hierarchical picker **must reuse a flat picker internally**.

Conceptually:

```
HierarchicalPicker
 ├─ Navigation logic (state, path, transitions)
 ├─ Breadcrumb + context
 └─ FlatLevelPicker
       └─ renders children of current node
```

This avoids duplication and keeps SRP intact.

---

## 📦 Reference Implementation (MANDATORY BASE)

You MUST base your implementation on the following reference.
You may refactor and modularize it, but **do not change the interaction model**.

```python
# === HIERARCHICAL PICKER REFERENCE IMPLEMENTATION ===

from dataclasses import dataclass, field
from typing import Optional, List

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.styles import Style

from rich.console import Console
from rich.panel import Panel


@dataclass
class SelectionNode:
    id: str
    label: str
    kind: str
    children: List["SelectionNode"] = field(default_factory=list)
    payload: object | None = None
    preview: object | None = None


@dataclass
class PickerState:
    path: List[SelectionNode]
    current: SelectionNode
    filter: str = ""


class HierarchicalPickerImpl:
    def __init__(self, root: SelectionNode, title: str):
        self.state = PickerState(path=[root], current=root)
        self.title = title
        self.console = Console(force_terminal=True)

        self.search = TextArea(height=1, prompt="Search: ")

        self.list_control = FormattedTextControl(self._render_list, focusable=True)
        self.preview_control = FormattedTextControl(self._render_preview)

        self.kb = self._keybindings()

        layout = HSplit(
            [
                Window(content=FormattedTextControl(self._render_header), height=1),
                Window(content=FormattedTextControl(self._render_path), height=1),
                self.search,
                VSplit(
                    [
                        Window(self.list_control),
                        Window(width=1, char="|"),
                        Window(self.preview_control),
                    ],
                    padding=1,
                ),
            ]
        )

        self.app = Application(
            layout=Layout(layout, focused_element=self.search),
            key_bindings=self.kb,
            style=Style.from_dict({"selected": "reverse"}),
            full_screen=True,
        )

        self.search.buffer.on_text_changed += lambda _: self._apply_filter()

    def _children(self):
        if not self.state.filter:
            return self.state.current.children
        q = self.state.filter.lower()
        return [c for c in self.state.current.children if q in c.label.lower()]

    def _apply_filter(self):
        self.state.filter = self.search.text.strip()
        self.app.invalidate()

    def _render_header(self):
        return self.title

    def _render_path(self):
        return "Path: " + " > ".join(n.label for n in self.state.path)

    def _render_list(self):
        frags = []
        for i, node in enumerate(self._children()):
            frags.append(("", f" {node.label}\n"))
        return frags

    def _render_preview(self):
        children = self._children()
        if not children:
            return ANSI("")
        node = children[0]
        if node.preview is None:
            return ANSI("")
        with self.console.capture() as cap:
            self.console.print(node.preview)
        return ANSI(cap.get())

    def _keybindings(self):
        kb = KeyBindings()

        @kb.add("enter")
        def _(e):
            children = self._children()
            if not children:
                return
            node = children[0]
            if node.children:
                self.state.path.append(node)
                self.state.current = node
                self.search.text = ""
            else:
                e.app.exit(result=node)

        @kb.add("backspace")
        def _(e):
            if len(self.state.path) > 1:
                self.state.path.pop()
                self.state.current = self.state.path[-1]
                self.search.text = ""

        @kb.add("escape")
        def _(e):
            e.app.exit(result=None)

        return kb

    def run(self) -> Optional[SelectionNode]:
        return self.app.run()
```

This code defines:

* navigation model
* breadcrumb
* hierarchical descent/ascent
* Rich-based preview
* prompt_toolkit interaction

You must **clean it up**, **generalize it**, and expose it as a reusable component.

---

## 🧪 Testing Requirement

Provide a **HeadlessHierarchicalPicker** that:

* operates on `SelectionNode`
* selects deterministically
* does not import UI libraries

---

## ✅ Acceptance Criteria

The task is complete only if:

* The picker supports multi-level navigation
* The domain hierarchy is visible and explicit
* The picker is reusable and encapsulated
* Flat selection logic is not duplicated
* The component adheres to SRP and DIP
* A headless implementation exists
* CLI code interacts only with the picker interface

---

## 🚀 Final Instruction

Do not flatten the hierarchy.
Do not reintroduce ad-hoc prompts.
Do not mix navigation logic with domain logic.

Design a **professional-grade hierarchical picker** suitable for complex engineering CLIs.