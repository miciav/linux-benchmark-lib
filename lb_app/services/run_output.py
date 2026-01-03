"""Output parsing helpers for run orchestration."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from rich.markup import escape


def _slug_phase_label(phase: str) -> str:
    """Normalize phase labels for consistent rendering."""
    cleaned = phase.replace(":", "-").strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-").lower() or "run"


def format_bullet_line(
    phase: str,
    message: str,
    host_label: str | None = None,
) -> str:
    """Format a log line with a phase tag and optional host label."""
    phase_clean = _slug_phase_label(phase)
    host_prefix = f"({host_label}) " if host_label else ""
    return f"• [{phase_clean}] {host_prefix}{message}"


class _TaskTimer:
    """Track task durations based on Ansible task boundaries."""

    def __init__(self) -> None:
        self._task_phase: str | None = None
        self._task_message: str | None = None
        self._started_at: float | None = None

    def start(self, phase: str, message: str) -> tuple[str, str] | None:
        now = time.monotonic()
        previous = None
        if self._task_message and self._started_at is not None:
            previous = self._finish(now)
        self._task_phase = phase
        self._task_message = message
        self._started_at = now
        return previous

    def flush(self) -> tuple[str, str] | None:
        return self._finish(time.monotonic())

    def _finish(self, now: float) -> tuple[str, str] | None:
        if not self._task_message or self._started_at is None:
            return None
        elapsed = now - self._started_at
        phase = self._task_phase or "run"
        message = f"{self._task_message} done in {elapsed:.1f}s"
        self._task_phase = None
        self._task_message = None
        self._started_at = None
        return phase, message


def _extract_lb_event_data(line: str, token: str = "LB_EVENT") -> dict[str, Any] | None:
    """Extract LB_EVENT JSON payloads from noisy Ansible output."""
    token_idx = line.find(token)
    if token_idx == -1:
        return None

    payload = line[token_idx + len(token) :].strip()
    start = payload.find("{")
    if start == -1:
        return None

    # Walk the payload to find the matching closing brace to avoid picking up
    # trailing characters from debug output (e.g., quotes + extra braces).
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


def _extract_lb_task_data(line: str, token: str = "LB_TASK") -> dict[str, Any] | None:
    """Extract LB_TASK JSON payloads from Ansible callback output."""
    token_idx = line.find(token)
    if token_idx == -1:
        return None

    payload = line[token_idx + len(token) :].strip()
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


class AnsibleOutputFormatter:
    """Parses raw Ansible output stream and prints user-friendly status updates."""

    def __init__(self):
        # Greedy match so nested brackets in task names (e.g., role prefix + [run:...])
        # are captured in full.
        self.task_pattern = re.compile(r"TASK \[(.*)\]")
        self.bench_pattern = re.compile(r"Running benchmark: (.*)")
        self.current_phase = "Initializing"  # Default phase
        self.suppress_progress = False
        self.host_label: str = ""
        self.emit_task_timings = False
        self.emit_task_starts = False
        self._task_timer = _TaskTimer()
        self._last_timing_line: str | None = None
        self._always_show_tasks = (
            "workload_runner : Build repetitions list",
            "workload_runner : Run benchmark via local runner (per repetition)",
        )
        self._suppress_task_names = {
            "Skip polling if already finished",
            "Poll LB_EVENT stream",
            "Streaming indicator",
            "Update finished status",
            "Delay",
            "Initialize polling status",
            "workload_runner : Skip polling if already finished",
            "workload_runner : Poll LB_EVENT stream",
            "workload_runner : Streaming indicator",
            "workload_runner : Update finished status",
            "workload_runner : Delay",
            "workload_runner : Initialize polling status",
        }

    def set_phase(self, phase: str):
        self.current_phase = phase

    def process(
        self, text: str, end: str = "", log_sink: Callable[[str], None] | None = None
    ):
        if not text:
            return

        lines = text.splitlines()
        for line in lines:
            self._handle_line(line, log_sink=log_sink)

    def process_timing(
        self, text: str, end: str = "", log_sink: Callable[[str], None] | None = None
    ) -> None:
        """Emit task duration lines without altering raw output."""
        if not text:
            return

        lines = text.splitlines()
        for line in lines:
            self._handle_timing_line(line, log_sink=log_sink)

    def _emit(self, message: str, log_sink: Callable[[str], None] | None) -> None:
        """Send formatted message to optional sink."""
        if log_sink:
            log_sink(message)

    def _emit_bullet(
        self,
        phase: str,
        message: str,
        log_sink: Callable[[str], None] | None,
        host_label: str | None = None,
    ) -> None:
        label = host_label if host_label is not None else self.host_label
        rendered = format_bullet_line(phase, message, host_label=label or None)
        if self._should_skip_timing(rendered):
            return
        safe = escape(rendered)
        self._emit(safe, log_sink)
        if " done in " in rendered:
            self._last_timing_line = rendered

    @staticmethod
    def _slug_phase(phase: str) -> str:
        return _slug_phase_label(phase)

    def _should_skip_timing(self, rendered: str) -> bool:
        if " done in " not in rendered:
            return False
        return rendered == self._last_timing_line

    def _handle_line(self, line: str, log_sink: Callable[[str], None] | None = None):
        line = line.strip()
        if not line:
            return
        if self._maybe_emit_task_timing(line, log_sink):
            return
        if self._maybe_emit_progress(line, log_sink):
            return
        if "LB_EVENT" in line:
            return
        if self._maybe_emit_msg_line(line, log_sink):
            return
        self._maybe_flush_task_timing(line, log_sink)
        if self._is_noise_line(line):
            return
        if self._maybe_emit_task(line, log_sink):
            return
        if self._maybe_emit_benchmark_start(line, log_sink):
            return
        if line.startswith("changed:") or line.startswith('"changed":') or line.startswith("'changed':"):
            return
        if self._maybe_emit_interesting(line, log_sink):
            return
        if self._maybe_emit_error(line, log_sink):
            return
        self._emit(line, log_sink)

    def _handle_timing_line(
        self, line: str, log_sink: Callable[[str], None] | None = None
    ) -> None:
        line = line.strip()
        if not line:
            return
        self._maybe_flush_task_timing(line, log_sink)
        parsed = self._parse_task_line(line)
        if not parsed:
            return
        phase, message = parsed
        timing = self._task_timer.start(phase, message)
        if timing:
            timing_phase, timing_message = timing
            self._emit_bullet(timing_phase, timing_message, log_sink)

    def _maybe_emit_progress(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        progress = self._format_progress(line)
        if not progress:
            return False
        phase, message, host_label = progress
        self._emit_bullet(phase, message, log_sink, host_label=host_label)
        return True

    def _maybe_emit_task_timing(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        data = _extract_lb_task_data(line, token="LB_TASK")
        if not data:
            return False
        self.emit_task_starts = False
        raw_task = str(data.get("task") or "")
        if not raw_task:
            return True
        parsed = self._parse_task_name(raw_task)
        if not parsed:
            return True
        phase, message = parsed
        if self._should_suppress_task(raw_task, message, log_sink):
            return True
        status = str(data.get("status") or "").lower()
        if status in {"failed", "skipped", "unreachable"}:
            message = f"{message} {status}"
        else:
            duration = data.get("duration_s")
            if duration is None:
                duration = data.get("duration")
            if duration is not None:
                try:
                    duration_val = float(duration)
                    message = f"{message} done in {duration_val:.1f}s"
                except Exception:
                    pass
        host_label = str(data.get("host") or "") or None
        self._emit_bullet(phase, message, log_sink, host_label=host_label)
        return True

    def _maybe_emit_msg_line(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        lowered = line.strip()
        if not (lowered.startswith('"msg"') or lowered.startswith("'msg'") or lowered.startswith("msg:")):
            return False
        payload = line.split(":", 1)[1].strip()
        if "LB_EVENT" in payload:
            return True
        if "LB_TASK" in payload:
            return True
        message = payload
        if payload and payload[0] in {"'", '"'}:
            try:
                message = json.loads(payload)
            except Exception:
                message = payload.strip("\"'")
        self._emit_bullet(self.current_phase, str(message), log_sink)
        return True

    def _is_noise_line(self, line: str) -> bool:
        noise_tokens = {
            "PLAY [",
            "GATHERING FACTS",
            "RECAP",
            "ok:",
            "skipping:",
            "included:",
        }
        if line.startswith("TASK [") and not self.emit_task_starts:
            return True
        if line.strip() in {"{", "}"}:
            return True
        return any(token in line for token in noise_tokens) or line.startswith("*****")

    def _maybe_emit_task(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        parsed = self._parse_task_line(line)
        if not parsed:
            return False
        phase, message = parsed
        raw_task = self.task_pattern.search(line).group(1).strip()
        if self._should_suppress_task(raw_task, message, log_sink):
            return True
        if self.emit_task_timings:
            timing = self._task_timer.start(phase, message)
            if timing:
                timing_phase, timing_message = timing
                self._emit_bullet(timing_phase, timing_message, log_sink)
            return True
        if not self.emit_task_starts:
            return True
        self._emit_bullet(phase, message, log_sink)
        return True

    def _parse_task_line(self, line: str) -> tuple[str, str] | None:
        task_match = self.task_pattern.search(line)
        if not task_match:
            return None
        raw_task = task_match.group(1).strip()
        return self._parse_task_name(raw_task)

    def _parse_task_name(self, raw_task: str) -> tuple[str, str] | None:
        task_name = raw_task.split(" : ", 1)[-1]
        phase = self.current_phase
        message = task_name
        if task_name.startswith("[") and "]" in task_name:
            closing = task_name.find("]")
            embedded = task_name[1:closing]
            message = task_name[closing + 1 :].strip() or raw_task
            phase = embedded or self.current_phase
        if raw_task in self._always_show_tasks or task_name in self._always_show_tasks:
            message = task_name
        return phase, message

    def _should_suppress_task(
        self,
        raw_task: str,
        task_name: str,
        log_sink: Callable[[str], None] | None,
    ) -> bool:
        if raw_task in self._suppress_task_names or task_name in self._suppress_task_names:
            # Allow dashboard sinks to summarize polling tasks instead of dropping them.
            return log_sink is None
        return False

    def _maybe_flush_task_timing(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> None:
        if not self.emit_task_timings:
            return
        completion_tokens = (
            "ok:",
            "changed:",
            "skipping:",
            "failed:",
            "fatal:",
            "unreachable:",
            "included:",
        )
        if line.startswith("PLAY [") or line.startswith("PLAY RECAP") or line.startswith(completion_tokens):
            timing = self._task_timer.flush()
            if timing:
                timing_phase, timing_message = timing
                self._emit_bullet(timing_phase, timing_message, log_sink)

    def _maybe_emit_benchmark_start(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        bench_match = self.bench_pattern.search(line)
        if not bench_match:
            return False
        bench_name = bench_match.group(1)
        self._emit_bullet(self.current_phase, f"Benchmark: {bench_name}", log_sink)
        return True

    def _maybe_emit_interesting(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        interesting_tokens = (
            "lb_runner.engine.runner",
            "Running test",
            "Progress:",
            "Completed",
        )
        if any(token in line for token in interesting_tokens) or "━" in line:
            self._emit_bullet(self.current_phase, line, log_sink)
            return True
        return False

    def _maybe_emit_error(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        if "fatal:" in line or "ERROR" in line or "failed:" in line:
            self._emit_bullet(self.current_phase, f"[!] {line}", log_sink)
            return True
        return False

    def _format_progress(self, line: str) -> tuple[str, str, str | None] | None:
        """Render LB_EVENT progress lines into a concise message."""
        if self.suppress_progress:
            return None
        data = _extract_lb_event_data(line, token="LB_EVENT")
        if not data:
            return None
        host = str(data.get("host") or "")
        workload = str(data.get("workload") or "?")
        rep = data.get("repetition", "?")
        total = data.get("total_repetitions") or data.get("total") or "?"
        status = (data.get("status") or "").lower()
        evt_type = data.get("type", "status")

        if evt_type == "log":
            level = data.get("level", "INFO")
            msg = data.get("message", "")
            phase = f"run {workload}"
            return phase, f"[{level}] {msg}", host or None

        message = f"{rep}/{total} {status}"
        if data.get("message"):
            message = f"{message} ({data['message']})"
        phase = f"run {workload}"
        if status == "running":
            return phase, message, host or None
        if status == "done":
            return phase, message, host or None
        if status == "failed":
            return phase, message, host or None
        return phase, f"{rep}/{total} {status}", host or None
