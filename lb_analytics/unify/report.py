"""What a load did: files read, problems found, what was left out."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class LoadReport:
    files_read: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    undeclared_files: list[str] = field(default_factory=list)
    not_loadable: list[str] = field(default_factory=list)
    failed_repetitions: list[dict[str, Any]] = field(default_factory=list)
    ignored_columns: dict[str, list[str]] = field(default_factory=dict)
    missing_values: dict[str, int] = field(default_factory=dict)

    def error(self, source: str, message: str) -> None:
        self.errors.append({"source": source, "message": message})

    def warn(self, source: str, message: str) -> None:
        self.warnings.append({"source": source, "message": message})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
