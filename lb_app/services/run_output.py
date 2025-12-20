"""Output parsing helpers for run orchestration."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from rich.markup import escape


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
        self._always_show_tasks = (
            "workload_runner : Build repetitions list",
            "workload_runner : Run benchmark via local runner (per repetition)",
        )

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

    def _emit(self, message: str, log_sink: Callable[[str], None] | None) -> None:
        """Send formatted message to optional sink."""
        if log_sink:
            log_sink(message)

    def _emit_bullet(
        self, phase: str, message: str, log_sink: Callable[[str], None] | None
    ) -> None:
        phase_clean = self._slug_phase(phase)
        host_prefix = f"({self.host_label}) " if self.host_label else ""
        rendered = f"• [{phase_clean}] {host_prefix}{message}"
        safe = escape(rendered)
        self._emit(safe, log_sink)

    @staticmethod
    def _slug_phase(phase: str) -> str:
        """Normalize phase labels for consistent rendering."""
        cleaned = phase.replace(":", "-").strip()
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned)
        cleaned = re.sub(r"-{2,}", "-", cleaned)
        return cleaned.strip("-").lower() or "run"

    def _handle_line(self, line: str, log_sink: Callable[[str], None] | None = None):
        line = line.strip()
        if not line:
            return
        if self._maybe_emit_progress(line, log_sink):
            return
        if self._is_noise_line(line):
            return
        if self._maybe_emit_task(line, log_sink):
            return
        if self._maybe_emit_benchmark_start(line, log_sink):
            return
        if line.startswith("changed:"):
            return
        if self._maybe_emit_interesting(line, log_sink):
            return
        if self._maybe_emit_error(line, log_sink):
            return
        self._emit(line, log_sink)

    def _maybe_emit_progress(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        progress = self._format_progress(line)
        if not progress:
            return False
        phase, message = progress
        self._emit_bullet(phase, message, log_sink)
        return True

    @staticmethod
    def _is_noise_line(line: str) -> bool:
        noise_tokens = {
            "PLAY [",
            "GATHERING FACTS",
            "RECAP",
            "ok:",
            "skipping:",
            "included:",
        }
        return any(token in line for token in noise_tokens) or line.startswith("*****")

    def _maybe_emit_task(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        task_match = self.task_pattern.search(line)
        if not task_match:
            return False
        raw_task = task_match.group(1).strip()
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
        self._emit_bullet(phase, message, log_sink)
        return True

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
            "lb_runner.local_runner",
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

    def _format_progress(self, line: str) -> tuple[str, str] | None:
        """Render LB_EVENT progress lines into a concise message."""
        if self.suppress_progress:
            return None
        data = _extract_lb_event_data(line, token="LB_EVENT")
        if not data:
            return None
        host = data.get("host", "?")
        workload = data.get("workload", "?")
        rep = data.get("repetition", "?")
        total = data.get("total_repetitions") or data.get("total") or "?"
        status = (data.get("status") or "").lower()
        evt_type = data.get("type", "status")

        if evt_type == "log":
            level = data.get("level", "INFO")
            msg = data.get("message", "")
            phase = f"run {host} {workload}"
            return phase, f"[{level}] {msg}"

        message = f"{rep}/{total} {status}"
        if data.get("message"):
            message = f"{message} ({data['message']})"
        phase = f"run {host} {workload}"
        if status == "running":
            return phase, message
        if status == "done":
            return phase, message
        if status == "failed":
            return phase, message
        return phase, f"{rep}/{total} {status}"
