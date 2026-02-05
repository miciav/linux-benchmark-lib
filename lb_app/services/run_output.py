"""Output parsing helpers for run orchestration."""

from __future__ import annotations

import re
from typing import Callable

from rich.markup import escape

from .run_output_formatting import (
    _slug_phase_label,
    format_bullet_line,
    format_progress_line,
)
from .run_output_parsing import _extract_lb_event_data  # noqa: F401
from .run_output_parsing import (
    _extract_lb_task_data,
    extract_benchmark_name,
    extract_msg_line,
    extract_task_name,
    is_changed_line,
    is_error_line,
    is_interesting_line,
    is_noise_line,
    normalize_line,
)
from .run_output_timing import TaskTimer


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
        self._task_timer = TaskTimer()
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
        line = normalize_line(line)
        if line is None:
            return
        if self._handle_early_line(line, log_sink):
            return
        self._maybe_flush_task_timing(line, log_sink)
        if self._handle_late_line(line, log_sink):
            return
        self._emit(line, log_sink)

    def _handle_early_line(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        if self._maybe_emit_task_timing(line, log_sink):
            return True
        if self._maybe_emit_progress(line, log_sink):
            return True
        if "LB_EVENT" in line:
            return True
        return self._maybe_emit_msg_line(line, log_sink)

    def _handle_late_line(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        if is_noise_line(line, emit_task_starts=self.emit_task_starts):
            return True
        if self._maybe_emit_task(line, log_sink):
            return True
        if self._maybe_emit_benchmark_start(line, log_sink):
            return True
        if is_changed_line(line):
            return True
        if self._maybe_emit_interesting(line, log_sink):
            return True
        return self._maybe_emit_error(line, log_sink)

    def _handle_timing_line(
        self, line: str, log_sink: Callable[[str], None] | None = None
    ) -> None:
        line = normalize_line(line)
        if line is None:
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
        message = self._format_task_timing_message(message, data)
        host_label = str(data.get("host") or "") or None
        self._emit_bullet(phase, message, log_sink, host_label=host_label)
        return True

    @staticmethod
    def _format_task_timing_message(message: str, data: dict[str, Any]) -> str:
        status = str(data.get("status") or "").lower()
        if status in {"failed", "skipped", "unreachable"}:
            return f"{message} {status}"
        duration = data.get("duration_s")
        if duration is None:
            duration = data.get("duration")
        if duration is None:
            return message
        try:
            duration_val = float(duration)
        except Exception:
            return message
        return f"{message} done in {duration_val:.1f}s"

    def _maybe_emit_msg_line(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        msg_line = extract_msg_line(line)
        if not msg_line:
            return False
        if msg_line.has_lb_event or msg_line.has_lb_task:
            return True
        self._emit_bullet(self.current_phase, msg_line.message, log_sink)
        return True

    def _maybe_emit_task(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        parsed = self._parse_task_line(line)
        if not parsed:
            return False
        phase, message = parsed
        raw_task = extract_task_name(line, self.task_pattern) or ""
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
        raw_task = extract_task_name(line, self.task_pattern)
        if not raw_task:
            return None
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
        if (
            raw_task in self._suppress_task_names
            or task_name in self._suppress_task_names
        ):
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
        if (
            line.startswith("PLAY [")
            or line.startswith("PLAY RECAP")
            or line.startswith(completion_tokens)
        ):
            timing = self._task_timer.flush()
            if timing:
                timing_phase, timing_message = timing
                self._emit_bullet(timing_phase, timing_message, log_sink)

    def _maybe_emit_benchmark_start(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        bench_name = extract_benchmark_name(line, self.bench_pattern)
        if not bench_name:
            return False
        self._emit_bullet(self.current_phase, f"Benchmark: {bench_name}", log_sink)
        return True

    def _maybe_emit_interesting(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        if is_interesting_line(line):
            self._emit_bullet(self.current_phase, line, log_sink)
            return True
        return False

    def _maybe_emit_error(
        self, line: str, log_sink: Callable[[str], None] | None
    ) -> bool:
        if is_error_line(line):
            self._emit_bullet(self.current_phase, f"[!] {line}", log_sink)
            return True
        return False

    def _format_progress(self, line: str) -> tuple[str, str, str | None] | None:
        """Render LB_EVENT progress lines into a concise message."""
        return format_progress_line(line, suppress_progress=self.suppress_progress)
