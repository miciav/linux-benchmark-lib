"""Event tailing helpers for controller runs."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

# Debug logging for event tailer diagnostics
_DEBUG = os.getenv("LB_EVENT_DEBUG", "1").lower() in ("1", "true", "yes")


class JsonEventTailer:
    """Tail a JSONL event file and emit parsed events to a callback."""

    def __init__(
        self,
        path: Path,
        on_event: Callable[[dict[str, Any]], None],
        poll_interval: float = 0.1,
    ):
        self.path = path
        self.on_event = on_event
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pos = 0

    def start(self) -> None:
        self._stop.clear()
        # Start from end of file to skip events from previous runs
        try:
            self._pos = self.path.stat().st_size
        except FileNotFoundError:
            self._pos = 0
        if _DEBUG:
            debug_path = self.path.parent / "lb_events.tailer.debug.log"
            with debug_path.open("a") as f:
                f.write(f"[{time.time()}] Tailer started, path={self.path}, initial_pos={self._pos}\n")
        self._thread = threading.Thread(
            target=self._run, name="lb-event-tailer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        debug_path = self.path.parent / "lb_events.tailer.debug.log" if _DEBUG else None
        while not self._stop.is_set():
            try:
                size = self.path.stat().st_size
            except FileNotFoundError:
                time.sleep(self.poll_interval)
                continue

            if self._pos > size:
                self._pos = 0

            try:
                with self.path.open("r", encoding="utf-8") as fp:
                    fp.seek(self._pos)
                    # Use readline() instead of iteration to allow fp.tell()
                    # Python 3.13+ raises OSError when calling tell() after
                    # using the file iterator (for line in fp)
                    while True:
                        line = fp.readline()
                        if not line:
                            break
                        self._pos = fp.tell()
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except Exception:
                            if debug_path:
                                with debug_path.open("a") as f:
                                    f.write(f"[{time.time()}] JSON parse error: {line[:100]!r}\n")
                            continue
                        if debug_path:
                            with debug_path.open("a") as f:
                                f.write(f"[{time.time()}] Read event: {data}\n")
                        self.on_event(data)
            except Exception as e:
                if debug_path:
                    with debug_path.open("a") as f:
                        f.write(f"[{time.time()}] Error reading file: {e}\n")

            time.sleep(self.poll_interval)
