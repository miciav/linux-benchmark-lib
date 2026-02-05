"""Parsing helpers for run output payloads."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Pattern

NOISE_TOKENS = {
    "PLAY [",
    "GATHERING FACTS",
    "RECAP",
    "ok:",
    "skipping:",
    "included:",
}

INTERESTING_TOKENS = (
    "lb_runner.engine.runner",
    "Running test",
    "Progress:",
    "Completed",
)


@dataclass(frozen=True)
class MsgLine:
    """Parsed msg line payload."""

    message: str
    has_lb_event: bool
    has_lb_task: bool


def normalize_line(line: str) -> str | None:
    """Normalize line text by trimming whitespace."""
    stripped = line.strip()
    return stripped or None


def _extract_lb_event_data(line: str, token: str = "LB_EVENT") -> dict[str, Any] | None:
    """Extract LB_EVENT JSON payloads from noisy Ansible output."""
    return _extract_tagged_json(line, token)


def _extract_lb_task_data(line: str, token: str = "LB_TASK") -> dict[str, Any] | None:
    """Extract LB_TASK JSON payloads from Ansible callback output."""
    return _extract_tagged_json(line, token)


def _extract_tagged_json(line: str, token: str) -> dict[str, Any] | None:
    token_idx = line.find(token)
    if token_idx == -1:
        return None

    payload = line[token_idx + len(token) :].strip()
    start, end = _find_json_bounds(payload)
    if start is None or end is None:
        return None
    raw = payload[start:end]
    return _parse_json_candidates(raw)


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


def _parse_json_candidates(raw: str) -> dict[str, Any] | None:
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


def extract_msg_line(line: str) -> MsgLine | None:
    """Extract message payloads from Ansible msg output lines."""
    lowered = line.strip()
    if not (
        lowered.startswith('"msg"')
        or lowered.startswith("'msg'")
        or lowered.startswith("msg:")
    ):
        return None
    payload = line.split(":", 1)[1].strip()
    has_lb_event = "LB_EVENT" in payload
    has_lb_task = "LB_TASK" in payload
    if payload and payload[0] in {"'", '"'}:
        try:
            message = json.loads(payload)
        except Exception:
            message = payload.strip("\"'")
    else:
        message = payload
    return MsgLine(
        message=str(message),
        has_lb_event=has_lb_event,
        has_lb_task=has_lb_task,
    )


def extract_task_name(line: str, task_pattern: Pattern[str]) -> str | None:
    """Extract raw task names from TASK lines."""
    match = task_pattern.search(line)
    if not match:
        return None
    return match.group(1).strip()


def extract_benchmark_name(line: str, bench_pattern: Pattern[str]) -> str | None:
    """Extract benchmark names from runner output."""
    match = bench_pattern.search(line)
    if not match:
        return None
    return match.group(1)


def is_noise_line(line: str, *, emit_task_starts: bool) -> bool:
    """Return True when the line is considered unhelpful noise."""
    if line.startswith("TASK [") and not emit_task_starts:
        return True
    if line.strip() in {"{", "}"}:
        return True
    return any(token in line for token in NOISE_TOKENS) or line.startswith("*****")


def is_changed_line(line: str) -> bool:
    """Return True when the line indicates Ansible 'changed' output."""
    return (
        line.startswith("changed:")
        or line.startswith('"changed":')
        or line.startswith("'changed':")
    )


def is_interesting_line(line: str) -> bool:
    """Return True when the line should be elevated for display."""
    return any(token in line for token in INTERESTING_TOKENS) or "━" in line


def is_error_line(line: str) -> bool:
    """Return True when the line indicates an error."""
    return "fatal:" in line or "ERROR" in line or "failed:" in line
