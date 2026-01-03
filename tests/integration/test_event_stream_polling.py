"""Integration test for streaming LB_EVENT lines from a growing log file."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from lb_controller.ansible.callback_plugins.lb_events import _extract_lb_event


def _append_lines(log_path: Path, lines: list[tuple[str, float]]) -> None:
    with log_path.open("ab") as handle:
        for line, delay_s in lines:
            time.sleep(delay_s)
            handle.write((line + "\n").encode("utf-8"))
            handle.flush()


def _tail_once(
    log_path: Path,
    offset_path: Path,
    stop_path: Path,
    workload: str,
    repetition: int,
) -> tuple[list[str], bool]:
    offset = 0
    try:
        offset = int(offset_path.read_text(encoding="utf-8").strip() or 0)
    except Exception:
        offset = 0

    if stop_path.exists():
        return [], True

    if not log_path.exists():
        return [], False

    emitted: list[str] = []
    found = False
    with log_path.open("rb") as handle:
        handle.seek(offset)
        while True:
            pos_before = handle.tell()
            line = handle.readline()
            if not line:
                break
            pos_after = handle.tell()
            if not line.endswith(b"\n"):
                offset = pos_before
                break
            offset = pos_after
            if b"LB_EVENT" not in line:
                continue
            decoded = line.decode("utf-8", errors="ignore").rstrip("\n")
            emitted.append(decoded)
            event = _extract_lb_event(decoded)
            if event and event.get("workload") == workload:
                if int(event.get("repetition", 0)) == repetition:
                    status = str(event.get("status", "")).lower()
                    if status in ("done", "failed", "stopped"):
                        found = True

    offset_path.write_text(str(offset), encoding="utf-8")
    return emitted, found


@pytest.mark.inter_generic
def test_lb_event_stream_emits_during_long_run(tmp_path: Path) -> None:
    """Ensure polling sees running events before completion."""
    log_path = tmp_path / "lb_events.stream.log"
    offset_path = tmp_path / "lb_events.offset"
    stop_path = tmp_path / "STOP"
    log_path.write_bytes(b"")
    offset_path.write_text("0", encoding="utf-8")

    workload = "dfaas"
    repetition = 1
    running_payload = {
        "run_id": "run-1",
        "host": "host-1",
        "workload": workload,
        "repetition": repetition,
        "total_repetitions": 1,
        "status": "running",
        "message": "config 1/2",
    }
    done_payload = {
        "run_id": "run-1",
        "host": "host-1",
        "workload": workload,
        "repetition": repetition,
        "total_repetitions": 1,
        "status": "done",
        "message": "duration=1.0s",
    }
    lines = [
        ("noise line", 0.05),
        (f"LB_EVENT {json.dumps(running_payload)}", 0.05),
        (f"LB_EVENT {json.dumps(done_payload)}", 0.2),
    ]
    writer = threading.Thread(target=_append_lines, args=(log_path, lines), daemon=True)
    writer.start()

    seen_lines: list[str] = []
    found = False
    deadline = time.time() + 2.0
    while time.time() < deadline and not found:
        emitted, found = _tail_once(
            log_path=log_path,
            offset_path=offset_path,
            stop_path=stop_path,
            workload=workload,
            repetition=repetition,
        )
        seen_lines.extend(emitted)
        time.sleep(0.05)

    writer.join(timeout=1.0)
    assert found is True
    assert any("status" in (_extract_lb_event(line) or {}) for line in seen_lines)
    assert any(
        (_extract_lb_event(line) or {}).get("status") == "running"
        for line in seen_lines
    )
