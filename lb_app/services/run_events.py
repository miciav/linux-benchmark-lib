"""Event tailing helpers for controller runs."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable


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
        self._thread = threading.Thread(
            target=self._run, name="lb-event-tailer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
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
                    for line in fp:
                        self._pos = fp.tell()
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except Exception:
                            continue
                        self.on_event(data)
            except Exception:
                pass

            time.sleep(self.poll_interval)
