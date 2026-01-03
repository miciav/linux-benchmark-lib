"""
Ansible callback plugin that captures LB_EVENT payloads and writes them to JSONL.

This runs on the controller side (not on remote hosts) and is enabled via
ANSIBLE_CALLBACK_PLUGINS + ANSIBLE_CALLBACKS_ENABLED. It looks for LB_EVENT
markers in task results (msg/stdout/stderr) and appends structured events to
LB_EVENT_LOG_PATH.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List

try:
    from ansible.plugins.callback import CallbackBase
except ModuleNotFoundError:  # pragma: no cover
    # Allow importing this module without the heavy `ansible` dependency installed.
    # The callback plugin itself is only usable when Ansible is present.
    class CallbackBase:  # type: ignore[no-redef]
        """Fallback base class used when Ansible isn't installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None


def _extract_lb_event(text: str) -> Dict[str, Any] | None:
    """Extract a JSON object that follows an LB_EVENT token inside text."""
    if "LB_EVENT" not in text:
        return None
    token_idx = text.find("LB_EVENT")
    payload = text[token_idx + len("LB_EVENT"):].strip()
    start = payload.find("{")
    if start == -1:
        return None
    depth = 0
    end: int | None = None
    for idx, ch in enumerate(payload[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    if end is None:
        return None

    raw = payload[start:end]
    candidates = (
        raw,
        raw.strip("\"'"),
        raw.replace(r"\"", '"'),
        raw.strip("\"'").replace(r"\"", '"'),
    )
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


class CallbackModule(CallbackBase):
    """
    Write LB_EVENT payloads to a JSONL file for consumption by the controller.
    """

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "lb_events"
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self) -> None:
        super().__init__()
        log_path = os.getenv("LB_EVENT_LOG_PATH") or "lb_events.jsonl"
        self.log_path = Path(log_path).expanduser()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._task_start_times: Dict[str, float] = {}
        # Debug mode: write diagnostic info to separate file
        # Temporarily enabled by default for diagnostics
        self._debug = os.getenv("LB_EVENT_DEBUG", "1").lower() in ("1", "true", "yes")
        self._debug_path = self.log_path.parent / "lb_events.debug.log" if self._debug else None
        if self._debug_path:
            self._debug_path.write_text(f"[{time.time()}] Callback plugin initialized, log_path={self.log_path}\n")

    def v2_runner_on_ok(self, result, **kwargs):  # type: ignore[override]
        self._handle_result(result, status_override=None)

    def v2_runner_on_failed(self, result, **kwargs):  # type: ignore[override]
        self._handle_result(result, status_override="failed")

    def v2_runner_on_unreachable(self, result, **kwargs):  # type: ignore[override]
        self._handle_result(result, status_override="unreachable")

    def v2_runner_on_skipped(self, result, **kwargs):  # type: ignore[override]
        self._handle_result(result, status_override="skipped")

    def v2_playbook_on_task_start(self, task, is_conditional=False):  # type: ignore[override]
        _ = is_conditional
        task_id = getattr(task, "_uuid", None)
        if task_id is None:
            return
        self._task_start_times[str(task_id)] = time.monotonic()

    # --- helpers ---

    def _handle_result(self, result: Any, status_override: str | None) -> None:
        host = getattr(result._host, "get_name", lambda: None)()  # type: ignore[attr-defined]
        task = getattr(result, "_task", None)
        task_name = getattr(task, "get_name", lambda: "")() if task else ""
        if self._debug and self._debug_path:
            res = getattr(result, "_result", {}) or {}
            stdout = res.get("stdout", "")[:200] if res.get("stdout") else ""
            msg = res.get("msg", "")[:200] if res.get("msg") else ""
            has_lb_event = "LB_EVENT" in str(res)
            with self._debug_path.open("a") as f:
                f.write(f"[{time.time()}] _handle_result: host={host} task={task_name} "
                        f"has_lb_event={has_lb_event} stdout_preview={stdout!r} msg_preview={msg!r}\n")
        for event in self._events_from_result(result):
            event.setdefault("host", host)
            if status_override and "status" not in event:
                event["status"] = status_override
            self._write_event(event)
            if self._debug and self._debug_path:
                with self._debug_path.open("a") as f:
                    f.write(f"[{time.time()}] Wrote event: {json.dumps(event)}\n")
        self._emit_task_timing(result, host, status_override)

    def _events_from_result(self, result: Any) -> Iterator[Dict[str, Any]]:
        payloads = list(self._candidate_texts(result))
        for text in payloads:
            event = _extract_lb_event(text)
            if event:
                yield event

    def _candidate_texts(self, result: Any) -> Iterable[str]:
        res = getattr(result, "_result", {}) or {}
        fields: List[str] = []
        for key in ("msg", "stdout", "stderr"):
            val = res.get(key)
            if isinstance(val, str):
                fields.append(val)
        for key in ("stdout_lines", "stderr_lines"):
            val = res.get(key)
            if isinstance(val, list):
                fields.extend(str(x) for x in val)
        # Loop results (e.g., include_tasks)
        loop_results = res.get("results")
        if isinstance(loop_results, list):
            for item in loop_results:
                if isinstance(item, dict):
                    for key in ("msg", "stdout", "stderr"):
                        val = item.get(key)
                        if isinstance(val, str):
                            fields.append(val)
        return fields

    def _write_event(self, event: Dict[str, Any]) -> None:
        try:
            with self.log_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(event) + "\n")
        except Exception:
            # Callback errors must never break Ansible execution.
            return

    def _emit_task_timing(
        self, result: Any, host: str | None, status_override: str | None
    ) -> None:
        task = getattr(result, "_task", None)
        task_id = getattr(task, "_uuid", None)
        if task_id is None:
            return
        start = self._task_start_times.get(str(task_id))
        if start is None:
            return
        duration_s = max(0.0, time.monotonic() - start)
        task_name = ""
        if task is not None:
            task_name = getattr(task, "get_name", lambda: "")() or ""
        payload = {
            "host": host or "",
            "task": task_name,
            "duration_s": round(duration_s, 3),
            "status": status_override or "ok",
        }
        try:
            self._display.display(f"LB_TASK {json.dumps(payload)}")
        except Exception:
            return
