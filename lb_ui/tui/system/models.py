from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TableModel:
    title: str
    columns: list[str]
    rows: list[list[str]]


@dataclass(frozen=True)
class PickItem:
    id: str
    title: str
    tags: tuple[str, ...] = ()
    description: str = ""
    search_blob: str = ""
    preview: object | None = None  # Rich renderable
    payload: Any = None  # domain object
    variants: Sequence["PickItem"] = ()  # Nested options (e.g. intensities)
    selected: bool = False
    disabled: bool = False


@dataclass
class SelectionNode:
    id: str
    label: str
    kind: str  # e.g. "category", "plugin", "profile", "option"
    children: list["SelectionNode"] = field(default_factory=list)
    payload: Any | None = None  # domain object
    preview: object | None = None  # Rich renderable (optional)
