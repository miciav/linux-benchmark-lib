"""Log rollup helpers for RichDashboard."""

from __future__ import annotations

from typing import Dict, Tuple

from rich.markup import escape


POLLING_TASKS = frozenset(
    {
        "Skip polling if already finished",
        "Poll LB_EVENT stream",
        "Streaming indicator",
        "Update finished status",
        "Delay",
    }
)


class PollingRollupHelper:
    """Parse and summarize polling-loop log entries."""

    def __init__(self, log_buffer: list[str], *, summary_only: bool = True) -> None:
        self._log_buffer = log_buffer
        self._summary_only = summary_only
        self._rollups: Dict[Tuple[str, str, str, str], dict[str, float | int]] = {}

    def maybe_rollup(self, message: str) -> bool:
        parsed = self._parse_bullet_line(self._normalize_log_line(message))
        if not parsed:
            return False
        phase, host, task_message = parsed
        base = task_message
        if base.startswith("workload_runner : "):
            base = base.split(" : ", 1)[1].strip()
        duration: float | None = None
        status = ""
        if " done in " in base:
            base, timing = base.rsplit(" done in ", 1)
            base = base.strip()
            if timing.endswith("s"):
                try:
                    duration = float(timing[:-1])
                except Exception:
                    duration = None
            status = "done"
        else:
            for token in ("skipped", "failed", "unreachable"):
                suffix = f" {token}"
                if base.endswith(suffix):
                    base = base[: -len(suffix)].strip()
                    status = token
                    break
        if base not in POLLING_TASKS:
            return False
        if status in {"failed", "unreachable"}:
            return False
        if status == "" and duration is None:
            return False
        status_key = status or "done"
        key = (phase, host, base, status_key)
        rollup = self._rollups.get(key, {"count": 0, "duration": 0.0})
        rollup["count"] = int(rollup["count"]) + 1
        if duration is not None:
            rollup["duration"] = float(rollup["duration"]) + duration
        self._rollups[key] = rollup
        if self._summary_only:
            self._update_polling_summary(phase, host)
            return True
        count = int(rollup["count"])
        if status_key == "skipped":
            display_message = f"{base} x{count} skipped"
        else:
            total = float(rollup["duration"])
            display_message = f"{base} x{count} done in {total:.1f}s"
        host_prefix = f"({host}) " if host else ""
        display_line = escape(f"• [{phase}] {host_prefix}{display_message}")
        search_prefix = f"• [{phase}] {host_prefix}{base} "
        for idx in range(len(self._log_buffer) - 1, -1, -1):
            existing = self._normalize_log_line(self._log_buffer[idx])
            if not existing.startswith(search_prefix):
                continue
            if status_key == "skipped" and not existing.endswith("skipped"):
                continue
            if status_key != "skipped" and " done in " not in existing:
                continue
            self._log_buffer[idx] = display_line
            return True
        self._log_buffer.append(display_line)
        return True

    def _update_polling_summary(self, phase: str, host: str) -> None:
        poll_key = (phase, host, "Poll LB_EVENT stream", "done")
        delay_key = (phase, host, "Delay", "done")
        poll_rollup = self._rollups.get(poll_key, {"count": 0, "duration": 0.0})
        delay_rollup = self._rollups.get(delay_key, {"count": 0, "duration": 0.0})
        skipped_count = 0
        for (r_phase, r_host, _, status), rollup in self._rollups.items():
            if r_phase == phase and r_host == host and status == "skipped":
                skipped_count += int(rollup.get("count", 0))

        poll_count = int(poll_rollup.get("count", 0))
        poll_total = float(poll_rollup.get("duration", 0.0))
        delay_count = int(delay_rollup.get("count", 0))
        delay_total = float(delay_rollup.get("duration", 0.0))
        if poll_count == 0 and delay_count == 0 and skipped_count == 0:
            return

        parts: list[str] = []
        if poll_count:
            parts.append(f"poll x{poll_count} {poll_total:.1f}s")
        if delay_count:
            parts.append(f"delay x{delay_count} {delay_total:.1f}s")
        if skipped_count:
            parts.append(f"skipped x{skipped_count}")
        summary_message = "Polling loop " + " ".join(parts)
        host_prefix = f"({host}) " if host else ""
        display_line = escape(f"• [{phase}] {host_prefix}{summary_message}")
        search_prefix = f"• [{phase}] {host_prefix}Polling loop "
        for idx in range(len(self._log_buffer) - 1, -1, -1):
            existing = self._normalize_log_line(self._log_buffer[idx])
            if existing.startswith(search_prefix):
                self._log_buffer[idx] = display_line
                return
        self._log_buffer.append(display_line)

    @staticmethod
    def _normalize_log_line(line: str) -> str:
        return line.replace("\\[", "[").replace("\\]", "]")

    @staticmethod
    def _parse_bullet_line(line: str) -> tuple[str, str, str] | None:
        if not line.startswith("• "):
            return None
        rest = line[2:].lstrip()
        if not rest.startswith("["):
            return None
        close = rest.find("]")
        if close == -1:
            return None
        phase = rest[1:close].strip()
        rest = rest[close + 1 :].lstrip()
        host = ""
        if rest.startswith("(") and ")" in rest:
            close_host = rest.find(")")
            host = rest[1:close_host].strip()
            rest = rest[close_host + 1 :].lstrip()
        message = rest.strip()
        if not phase or not message:
            return None
        return phase, host, message
