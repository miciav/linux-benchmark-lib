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
                f.write(
                    f"[{time.time()}] Tailer started, path={self.path}, "
                    f"initial_pos={self._pos}\n"
                )
        self._thread = threading.Thread(
            target=self._run, name="lb-event-tailer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    @staticmethod
    def _debug_path(base_path: Path) -> Path | None:
        if _DEBUG:
            return base_path.parent / "lb_events.tailer.debug.log"
        return None

    @staticmethod
    def _write_debug(debug_path: Path | None, message: str) -> None:
        if not debug_path:
            return
        with debug_path.open("a") as f:
            f.write(f"[{time.time()}] {message}\n")

    def _refresh_file_size(self, debug_path: Path | None) -> bool:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            time.sleep(self.poll_interval)
            return False

        if self._pos > size:
            self._pos = 0
        return True

    def _parse_json(self, line: str, debug_path: Path | None) -> dict[str, Any] | None:
        try:
            return json.loads(line)
        except Exception:
            self._write_debug(debug_path, f"JSON parse error: {line[:100]!r}")
            return None

    def _handle_line(self, line: str, debug_path: Path | None) -> None:
        line = line.strip()
        if not line:
            return
        data = self._parse_json(line, debug_path)
        if data is None:
            return
        self._write_debug(debug_path, f"Read event: {data}")
        self.on_event(data)

    def _consume_lines(self, fp: Any, debug_path: Path | None) -> None:
        while True:
            line = fp.readline()
            if not line:
                return
            self._pos = fp.tell()
            self._handle_line(line, debug_path)

    def _run(self) -> None:
        debug_path = self._debug_path(self.path)
        while not self._stop.is_set():
            if not self._refresh_file_size(debug_path):
                continue

            try:
                with self.path.open("r", encoding="utf-8") as fp:
                    fp.seek(self._pos)
                    # Use readline() instead of iteration to allow fp.tell()
                    # Python 3.13+ raises OSError when calling tell() after
                    # using the file iterator (for line in fp)
                    self._consume_lines(fp, debug_path)
            except Exception as exc:
                self._write_debug(debug_path, f"Error reading file: {exc}")

            time.sleep(self.poll_interval)
