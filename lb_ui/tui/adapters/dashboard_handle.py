from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
import queue
import threading
from typing import Any

from lb_ui.tui.core.protocols import Dashboard


class DashboardHandleAdapter(Dashboard):
    def __init__(self, sink: Dashboard, *, threaded: bool = False) -> None:
        self._sink = sink
        self._threaded = threaded
        self._queue: queue.Queue[tuple[str, tuple[Any, ...], dict[str, Any]] | None] | None = None
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None
        if threaded:
            self._queue = queue.Queue()
            self._stop = threading.Event()

    @contextmanager
    def live(self) -> AbstractContextManager[None]:
        if not self._threaded:
            with self._sink.live():
                yield self
            return
        assert self._queue is not None
        assert self._stop is not None
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="lb-dashboard-thread", daemon=True
        )
        self._thread.start()
        try:
            yield self
        finally:
            self._stop.set()
            self._queue.put(None)
            if self._thread:
                self._thread.join(timeout=2)
                self._thread = None

    def _run(self) -> None:
        assert self._queue is not None
        assert self._stop is not None
        with self._sink.live():
            while not self._stop.is_set():
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is None:
                    break
                method, args, kwargs = item
                try:
                    getattr(self._sink, method)(*args, **kwargs)
                    if method != "refresh":
                        self._sink.refresh()
                except Exception:
                    continue

    def _dispatch(self, method: str, *args: Any, **kwargs: Any) -> None:
        if not self._threaded:
            getattr(self._sink, method)(*args, **kwargs)
            return
        assert self._queue is not None
        self._queue.put((method, args, kwargs))

    def add_log(self, line: str) -> None:
        self._dispatch("add_log", line)

    def refresh(self) -> None:
        self._dispatch("refresh")

    def mark_event(self, source: str) -> None:
        self._dispatch("mark_event", source)

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        self._dispatch("set_warning", message, ttl=ttl)

    def clear_warning(self) -> None:
        self._dispatch("clear_warning")

    def set_controller_state(self, state: str) -> None:
        self._dispatch("set_controller_state", state)
