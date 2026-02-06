"""Generic contracts for PEVA-faas scheduling, policy, and memory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


ConfigPairs = list[tuple[str, int]]
ConfigKey = tuple[tuple[str, ...], tuple[int, ...]]


@dataclass(frozen=True)
class ExecutionEvent:
    """Canonical execution payload passed to memory/policy components."""

    run_id: str
    config_id: str
    iteration: int
    repetition: int
    config_pairs: ConfigPairs
    config_key: ConfigKey
    started_at: float
    ended_at: float
    result_row: dict[str, Any]
    metrics: dict[str, Any]
    summary: dict[str, Any]
    output_dir: Path


@runtime_checkable
class ConfigScheduler(Protocol):
    """Select next configuration batch from available candidates."""

    def propose_batch(
        self,
        *,
        candidates: list[ConfigPairs],
        seen_keys: set[ConfigKey],
        desired_size: int,
    ) -> list[ConfigPairs]:
        """Return up to ``desired_size`` configs to execute next."""


@runtime_checkable
class PolicyAlgorithm(Protocol):
    """Policy behavior used for candidate prioritization and updates."""

    def choose_batch(
        self, *, candidates: list[ConfigPairs], desired_size: int
    ) -> list[ConfigPairs]:
        """Choose configuration batch from candidate set."""

    def update_online(self, event: ExecutionEvent) -> None:
        """Update policy state after one new event."""

    def update_batch(self, events: list[ExecutionEvent]) -> None:
        """Update policy state with a micro-batch of events."""


@runtime_checkable
class MemoryEngine(Protocol):
    """Persistent + in-memory execution history service."""

    def startup(self) -> None:
        """Initialize storage and load runtime cache."""

    def is_seen(self, key: ConfigKey) -> bool:
        """Return whether the config key is already known."""

    def ingest_event(self, event: ExecutionEvent) -> None:
        """Persist and index one execution event."""

    def checkpoint(self) -> None:
        """Persist checkpoint artifacts at the end of execution."""
