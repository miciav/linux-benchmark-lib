"""In-process memory engine composing store, cache, and policy updates."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from .contracts import ConfigKey, ExecutionEvent, PolicyAlgorithm
from .memory_checkpoint import ParquetCheckpoint
from .memory_store import DuckDBMemoryStore
from .tensor_cache import TensorCache


class InProcessMemoryEngine:
    """Runtime memory coordinator for online and micro-batch modes."""

    def __init__(
        self,
        *,
        mode: Literal["online", "micro_batch"],
        batch_size: int,
        batch_window_s: int,
        store: DuckDBMemoryStore,
        cache: TensorCache,
        policy: PolicyAlgorithm,
        checkpoint: ParquetCheckpoint | None = None,
        preload_core_dir: Path | None = None,
        export_core_dir: Path | None = None,
        export_debug_dir: Path | None = None,
    ) -> None:
        self._mode = mode
        self._batch_size = batch_size
        self._batch_window_s = batch_window_s
        self._store = store
        self._cache = cache
        self._policy = policy
        self._checkpoint = checkpoint
        self._preload_core_dir = preload_core_dir
        self._export_core_dir = export_core_dir
        self._export_debug_dir = export_debug_dir
        self._seen_keys: set[ConfigKey] = set()
        self._pending_events: list[ExecutionEvent] = []
        self._last_update_ts = time.time()

    def startup(self) -> None:
        """Initialize store and seed seen keys."""
        self._store.startup()
        if (
            self._checkpoint is not None
            and self._preload_core_dir is not None
            and self._preload_core_dir.exists()
        ):
            self._checkpoint.preload_core(self._preload_core_dir)
        self._seen_keys = set(self._store.load_seen_keys())

    def is_seen(self, key: ConfigKey) -> bool:
        """Check if key has already been observed."""
        return key in self._seen_keys

    def ingest_event(self, event: ExecutionEvent) -> None:
        """Persist and index one new execution event."""
        self._store.insert_execution_event(event)
        self._cache.add_event(event)
        self._seen_keys.add(event.config_key)

        if self._mode == "online":
            self._policy.update_online(event)
            return

        self._pending_events.append(event)
        now = time.time()
        reached_size = len(self._pending_events) >= self._batch_size
        reached_window = (now - self._last_update_ts) >= self._batch_window_s
        if reached_size or reached_window:
            self._policy.update_batch(self._pending_events)
            self._pending_events = []
            self._last_update_ts = now

    def checkpoint(self) -> None:
        """Flush pending updates and export checkpoint artifacts if configured."""
        if self._mode == "micro_batch" and self._pending_events:
            self._policy.update_batch(self._pending_events)
            self._pending_events = []

        if (
            self._checkpoint is not None
            and self._export_core_dir is not None
            and self._export_debug_dir is not None
        ):
            self._checkpoint.export_all(
                core_dir=self._export_core_dir,
                debug_dir=self._export_debug_dir,
            )

    def tensor_cache_size(self) -> int:
        """Return current number of cached vectors."""
        return self._cache.size()
