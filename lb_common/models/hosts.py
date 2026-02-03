"""Lightweight host definition shared across layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class RemoteHostSpec:
    """Host connection details without runner/controller dependencies."""

    name: str
    address: str
    port: int = 22
    user: str = "root"
    become: bool = True
    become_method: str = "sudo"
    vars: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_object(cls, host: Any) -> "RemoteHostSpec":
        """Create a spec from any object with matching attributes."""
        return cls(
            name=getattr(host, "name"),
            address=getattr(host, "address"),
            port=getattr(host, "port", 22),
            user=getattr(host, "user", "root"),
            become=getattr(host, "become", True),
            become_method=getattr(host, "become_method", "sudo"),
            vars=dict(getattr(host, "vars", {}) or {}),
        )
