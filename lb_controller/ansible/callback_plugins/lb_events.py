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
    payload = text[token_idx + len("LB_EVENT") :].strip()
    start, end = _find_json_bounds(payload)
    if start is None or end is None:
        return None
    raw = payload[start:end]
    return _parse_json_candidates(raw)


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
        self._debug_path = (
            self.log_path.parent / "lb_events.debug.log" if self._debug else None
        )
        if self._debug_path:
            self._debug_path.write_text(
                f"[{time.time()}] Callback plugin initialized, "
                f"log_path={self.log_path}\n"
            )

    def v2_runner_on_ok(self, result, **kwargs):  # type: ignore[override]
        self._handle_result(result, status_override=None)

    def v2_runner_on_failed(self, result, **kwargs):  # type: ignore[override]
        self._handle_result(result, status_override="failed")

    def v2_runner_on_unreachable(self, result, **kwargs):  # type: ignore[override]
        self._handle_result(result, status_override="unreachable")

    def v2_runner_on_skipped(self, result, **kwargs):  # type: ignore[override]
        self._handle_result(result, status_override="skipped")

    def v2_playbook_on_task_start(
        self, task, is_conditional: bool = False
    ):  # type: ignore[override]
        _ = is_conditional
        task_id = getattr(task, "_uuid", None)
        if task_id is None:
            return
        self._task_start_times[str(task_id)] = time.monotonic()

    # --- helpers ---

    def _handle_result(self, result: Any, status_override: str | None) -> None:
        host = _host_name(result)
        task_name = _task_name(result)
        self._log_debug_result(result, host, task_name)
        for event in self._events_from_result(result):
            self._emit_event(event, host, status_override)
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
        fields.extend(_collect_string_fields(res, ("msg", "stdout", "stderr")))
        fields.extend(_collect_list_fields(res, ("stdout_lines", "stderr_lines")))
        fields.extend(_collect_loop_fields(res))
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
        task_info = _task_info(result)
        if task_info is None:
            return
        task_id, task_name = task_info
        start = self._task_start_times.get(task_id)
        if start is None:
            return
        payload = _build_task_timing_payload(host, task_name, start, status_override)
        self._display_task_payload(payload)

    def _log_debug_result(self, result: Any, host: str, task_name: str) -> None:
        if not (self._debug and self._debug_path):
            return
        res = getattr(result, "_result", {}) or {}
        stdout = res.get("stdout", "")[:200] if res.get("stdout") else ""
        msg = res.get("msg", "")[:200] if res.get("msg") else ""
        has_lb_event = "LB_EVENT" in str(res)
        with self._debug_path.open("a") as f:
            f.write(
                f"[{time.time()}] _handle_result: host={host} task={task_name} "
                f"has_lb_event={has_lb_event} stdout_preview={stdout!r} "
                f"msg_preview={msg!r}\n"
            )

    def _emit_event(
        self,
        event: Dict[str, Any],
        host: str,
        status_override: str | None,
    ) -> None:
        event.setdefault("host", host)
        if status_override and "status" not in event:
            event["status"] = status_override
        self._write_event(event)
        self._log_debug_event(event)

    def _log_debug_event(self, event: Dict[str, Any]) -> None:
        if not (self._debug and self._debug_path):
            return
        with self._debug_path.open("a") as f:
            f.write(f"[{time.time()}] Wrote event: {json.dumps(event)}\n")

    def _display_task_payload(self, payload: Dict[str, Any]) -> None:
        try:
            self._display.display(f"LB_TASK {json.dumps(payload)}")
        except Exception:
            return


def _find_json_bounds(payload: str) -> tuple[int | None, int | None]:
    start = payload.find("{")
    if start == -1:
        return None, None
    depth = 0
    for idx, ch in enumerate(payload[start:], start):
        depth = _advance_json_depth(depth, ch)
        if depth == 0 and ch == "}":
            return start, idx + 1
    return None, None


def _advance_json_depth(depth: int, ch: str) -> int:
    if ch == "{":
        return depth + 1
    if ch == "}":
        return depth - 1
    return depth


def _parse_json_candidates(raw: str) -> Dict[str, Any] | None:
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


def _host_name(result: Any) -> str:
    return getattr(result._host, "get_name", lambda: "")()  # type: ignore[attr-defined]


def _task_name(result: Any) -> str:
    task = getattr(result, "_task", None)
    return getattr(task, "get_name", lambda: "")() if task else ""


def _task_info(result: Any) -> tuple[str, str] | None:
    task = getattr(result, "_task", None)
    task_id = getattr(task, "_uuid", None)
    if task_id is None:
        return None
    task_name = getattr(task, "get_name", lambda: "")() if task else ""
    return str(task_id), task_name


def _build_task_timing_payload(
    host: str | None,
    task_name: str,
    start: float,
    status_override: str | None,
) -> Dict[str, Any]:
    duration_s = max(0.0, time.monotonic() - start)
    return {
        "host": host or "",
        "task": task_name,
        "duration_s": round(duration_s, 3),
        "status": status_override or "ok",
    }


def _collect_string_fields(
    res: Dict[str, Any], keys: Iterable[str]
) -> List[str]:
    fields: List[str] = []
    for key in keys:
        val = res.get(key)
        if isinstance(val, str):
            fields.append(val)
    return fields


def _collect_list_fields(
    res: Dict[str, Any], keys: Iterable[str]
) -> List[str]:
    fields: List[str] = []
    for key in keys:
        val = res.get(key)
        if isinstance(val, list):
            fields.extend(str(x) for x in val)
    return fields


def _collect_loop_fields(res: Dict[str, Any]) -> List[str]:
    fields: List[str] = []
    loop_results = res.get("results")
    if not isinstance(loop_results, list):
        return fields
    for item in loop_results:
        if not isinstance(item, dict):
            continue
        fields.extend(_collect_string_fields(item, ("msg", "stdout", "stderr")))
    return fields
