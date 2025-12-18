"""Application-facing run orchestration helpers for the CLI."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import time
import re
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, is_dataclass
import threading
import hashlib
import json
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Callable, Dict, List, Optional
from types import SimpleNamespace

from lb_runner.benchmark_config import (
    BenchmarkConfig,
    RemoteHostConfig,
)
from lb_runner.events import RunEvent
from lb_runner.plugin_system.registry import PluginRegistry
from lb_runner.plugin_system.interface import WorkloadIntensity
from lb_runner.output_helpers import workload_output_dir
from lb_runner.stop_token import StopToken
from lb_controller.controller_runner import ControllerRunner
from lb_controller.controller_state import ControllerState
from lb_controller.journal import RunJournal, RunStatus, LogSink, TaskState
from lb_controller.ui_interfaces import UIAdapter, DashboardHandle, NoOpDashboardHandle
from rich.markup import escape

if TYPE_CHECKING:
    from ..controller import BenchmarkController, RunExecutionSummary


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


def _hash_config(cfg: BenchmarkConfig | None) -> str:
    """Return a stable hash for a BenchmarkConfig."""
    if cfg is None:
        return ""
    try:
        dump = cfg.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(dump, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    except Exception:
        try:
            return hashlib.sha256(str(cfg).encode("utf-8")).hexdigest()
        except Exception:
            return ""


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

        progress = self._format_progress(line)
        if progress:
            phase, message = progress
            self._emit_bullet(phase, message, log_sink)
            return

        # Filter noise
        if any(
            x in line
            for x in [
                "PLAY [",
                "GATHERING FACTS",
                "RECAP",
                "ok:",
                "skipping:",
                "included:",
            ]
        ):
            return
        if line.startswith("*****"):
            return

        # Format Tasks
        task_match = self.task_pattern.search(line)
        if task_match:
            raw_task = task_match.group(1).strip()
            task_name = raw_task
            # Cleanup "workload_runner :" prefix if present
            if " : " in task_name:
                _, task_name = task_name.split(" : ", 1)
            phase = self.current_phase
            message = task_name

            # If the task embeds a bracketed prefix, treat that as the phase.
            if task_name.startswith("[") and "]" in task_name:
                closing = task_name.find("]")
                embedded = task_name[1:closing]
                message = task_name[closing + 1 :].strip()
                phase = embedded or self.current_phase
                if not message:
                    message = raw_task

            # Show certain tasks even if they're "boring", but keep unified formatting.
            if (
                raw_task in self._always_show_tasks
                or task_name in self._always_show_tasks
            ):
                message = task_name

            self._emit_bullet(phase, message, log_sink)
            return

        # Format Benchmark Start (from python script)
        bench_match = self.bench_pattern.search(line)
        if bench_match:
            bench_name = bench_match.group(1)
            self._emit_bullet(self.current_phase, f"Benchmark: {bench_name}", log_sink)
            return

        # Format Changes (usually means success in ansible terms)
        if line.startswith("changed:"):
            return

        # Pass through interesting lines from the benchmark script
        if (
            "lb_runner.local_runner" in line
            or "Running test" in line
            or "Progress:" in line
            or "Completed" in line
        ):
            self._emit_bullet(self.current_phase, line, log_sink)
            return

        # Pass through raw output that looks like a progress bar (rich output often has special chars)
        if "━" in line:
            self._emit_bullet(self.current_phase, line, log_sink)
            return

        # Pass through errors
        if "fatal:" in line or "ERROR" in line or "failed:" in line:
            self._emit_bullet(self.current_phase, f"[!] {line}", log_sink)

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


@dataclass
class RunContext:
    """Inputs required to execute a run."""

    config: BenchmarkConfig
    target_tests: List[str]
    registry: PluginRegistry
    config_path: Optional[Path] = None
    debug: bool = False
    resume_from: str | None = None
    resume_latest: bool = False
    stop_file: Path | None = None
    execution_mode: str = "remote"


@dataclass
class RunResult:
    """Outcome of a run."""

    context: RunContext
    summary: Optional[RunExecutionSummary]
    journal_path: Path | None = None
    log_path: Path | None = None
    ui_log_path: Path | None = None


class _DashboardLogProxy(DashboardHandle):
    """Dashboard wrapper that also writes log lines to a file."""

    def __init__(self, inner: DashboardHandle, log_file: IO[str]):
        self._inner = inner
        self._log_file = log_file

    def live(self) -> AbstractContextManager[None]:
        return self._inner.live()

    def add_log(self, line: str) -> None:
        if not line or not str(line).strip():
            return
        message = str(line).strip()
        self._inner.add_log(message)
        try:
            self._log_file.write(message + "\n")
            self._log_file.flush()
        except Exception:
            pass

    def refresh(self) -> None:
        self._inner.refresh()

    def mark_event(self, source: str) -> None:
        self._inner.mark_event(source)


class RunService:
    """Coordinate benchmark execution for CLI commands."""

    def __init__(self, registry_factory: Callable[[], PluginRegistry]):
        self._registry_factory = registry_factory
        self._progress_token = "LB_EVENT"

    @staticmethod
    def _controller_stop_hint(message: str) -> tuple[str, str]:
        """Return colored dashboard text and plain log text for controller stop notices."""
        tag_plain = "[Controller]"
        tag_styled = "[bold bright_magenta][Controller][/bold bright_magenta]"
        base = message.lstrip()
        return f"{tag_styled} {base}", f"{tag_plain} {base}"

    def _enable_dashboard_log(
        self,
        dashboard: DashboardHandle,
        journal_path: Path,
    ) -> tuple[DashboardHandle, Path | None, IO[str] | None]:
        """Attach a ui_stream.log file to the dashboard when available."""
        if isinstance(dashboard, NoOpDashboardHandle):
            return dashboard, None, None
        ui_stream_log_path = journal_path.parent / "ui_stream.log"
        try:
            ui_stream_log_file = ui_stream_log_path.open("a", encoding="utf-8")
        except Exception:
            return dashboard, None, None
        wrapped = _DashboardLogProxy(dashboard, ui_stream_log_file)
        return wrapped, ui_stream_log_path, ui_stream_log_file

    def get_run_plan(
        self,
        cfg: BenchmarkConfig,
        tests: List[str],
        execution_mode: str = "remote",
        registry: PluginRegistry | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Build a detailed plan for the workloads to be run.

        Returns a list of dictionaries containing status, intensity, details, etc.
        """
        registry = registry or self._registry_factory()
        plan = []
        mode = (execution_mode or "remote").lower()

        for name in tests:
            wl = cfg.workloads.get(name)
            item = {
                "name": name,
                "plugin": wl.plugin if wl else "unknown",
                "status": "[yellow]?[/yellow]",
                "intensity": wl.intensity if wl else "-",
                "details": "-",
                "repetitions": str(cfg.repetitions),
            }

            if not wl:
                plan.append(item)
                continue

            try:
                plugin = registry.get(wl.plugin)
            except Exception:
                item["status"] = "[red]✗ (Missing)[/red]"
                plan.append(item)
                continue

            # Resolve Configuration (Preset vs Options)
            config_obj = None
            try:
                if wl.intensity and wl.intensity != "user_defined":
                    try:
                        level = WorkloadIntensity(wl.intensity)
                        config_obj = plugin.get_preset_config(level)
                    except ValueError:
                        pass  # Invalid intensity, will fall back

                # Fallback to user options if no preset found/used
                if config_obj is None:
                    # Instantiate config from dict
                    if isinstance(wl.options, dict):
                        config_obj = plugin.config_cls(**wl.options)
                    else:
                        config_obj = wl.options
            except Exception as e:
                item["details"] = f"[red]Config Error: {e}[/red]"

            # Format details string
            if config_obj:
                try:
                    # Convert to dict, filter None values
                    if isinstance(config_obj, dict):
                        data = config_obj
                    else:
                        try:
                            from pydantic import BaseModel

                            if isinstance(config_obj, BaseModel):
                                data = config_obj.model_dump()
                            elif is_dataclass(config_obj):
                                data = asdict(config_obj)
                            else:
                                data = {}
                        except Exception:
                            data = (
                                asdict(config_obj) if is_dataclass(config_obj) else {}
                            )
                    # Prioritize common fields for brevity
                    parts = []

                    # Duration/Timeout check
                    duration = (
                        data.get("timeout") or data.get("time") or data.get("runtime")
                    )
                    if duration:
                        parts.append(f"Time: {duration}s")

                    # Specific fields per plugin type
                    if "cpu_workers" in data and data["cpu_workers"] > 0:
                        parts.append(f"CPU: {data['cpu_workers']}")
                    if "vm_bytes" in data:
                        parts.append(f"VM: {data['vm_bytes']}")
                    if "bs" in data:
                        parts.append(f"BS: {data['bs']}")
                    if "count" in data and data["count"]:
                        parts.append(f"Count: {data['count']}")
                    if "parallel" in data:
                        parts.append(f"Streams: {data['parallel']}")
                    if "rw" in data:
                        parts.append(f"Mode: {data['rw']}")
                    if "iodepth" in data:
                        parts.append(f"Depth: {data['iodepth']}")

                    # Fallback if specific fields didn't cover much
                    if len(parts) < 2:
                        parts = [
                            f"{k}={v}"
                            for k, v in data.items()
                            if v is not None and k not in ["extra_args"]
                        ]

                    item["details"] = ", ".join(parts)
                except Exception:
                    item["details"] = str(config_obj)

            if mode == "docker":
                item["status"] = "[green]Docker (Ansible)[/green]"
                plan.append(item)
                continue

            if mode == "multipass":
                item["status"] = "[green]Multipass[/green]"
                plan.append(item)
                continue

            if mode == "remote":
                item["status"] = "[blue]Remote[/blue]"
                plan.append(item)
                continue

            item["status"] = "[yellow]?[/yellow]"

            plan.append(item)

        return plan

    @staticmethod
    def apply_overrides(
        cfg: BenchmarkConfig, intensity: str | None, debug: bool
    ) -> None:
        """Apply CLI-driven overrides to the configuration."""
        if intensity:
            for wl_name in cfg.workloads:
                cfg.workloads[wl_name].intensity = intensity
        if debug:
            for workload in cfg.workloads.values():
                if isinstance(workload.options, dict):
                    workload.options["debug"] = True
                else:
                    try:
                        setattr(workload.options, "debug", True)
                    except Exception:
                        pass

    def build_context(
        self,
        cfg: BenchmarkConfig,
        tests: Optional[List[str]],
        config_path: Optional[Path] = None,
        debug: bool = False,
        resume: Optional[str] = None,
        stop_file: Optional[Path] = None,
        execution_mode: str = "remote",
    ) -> RunContext:
        """Compute the run context and registry."""
        registry = self._registry_factory()
        target_tests = tests or [
            name for name, workload in cfg.workloads.items() if workload.enabled
        ]
        return RunContext(
            config=cfg,
            target_tests=target_tests,
            registry=registry,
            config_path=config_path,
            debug=debug,
            resume_from=None if resume in (None, "latest") else resume,
            resume_latest=resume == "latest",
            stop_file=stop_file,
            execution_mode=execution_mode,
        )

    def create_session(
        self,
        config_service: Any,
        tests: Optional[List[str]] = None,
        config_path: Optional[Path] = None,
        run_id: Optional[str] = None,
        resume: Optional[str] = None,
        repetitions: Optional[int] = None,
        debug: bool = False,
        intensity: Optional[str] = None,
        ui_adapter: UIAdapter | None = None,
        setup: bool = True,
        stop_file: Optional[Path] = None,
        execution_mode: str = "remote",
        preloaded_config: BenchmarkConfig | None = None,
    ) -> RunContext:
        """
        Orchestrate the creation of a RunContext from raw inputs.

        This method consolidates configuration loading, overrides, and context building.
        """
        # 1. Load Config (or reuse provided one)
        if preloaded_config is not None:
            cfg = preloaded_config
            resolved = config_path
            stale = None
        else:
            cfg, resolved, stale = config_service.load_for_read(config_path)
            if ui_adapter:
                if stale:
                    ui_adapter.show_warning(f"Saved default config not found: {stale}")
                if resolved:
                    ui_adapter.show_success(f"Loaded config: {resolved}")
                else:
                    ui_adapter.show_warning(
                        "No config file found; using built-in defaults."
                    )

        # 2. Overrides
        # Force setup flag from CLI onto the config, which drives logic in execute()
        cfg.remote_execution.run_setup = setup
        if not setup:
            cfg.remote_execution.run_teardown = False
        cfg.remote_execution.enabled = True

        if repetitions is not None:
            cfg.repetitions = repetitions
            if ui_adapter:
                ui_adapter.show_info(f"Using {repetitions} repetitions for this run")

        self.apply_overrides(cfg, intensity=intensity, debug=debug)
        if intensity and ui_adapter:
            ui_adapter.show_info(f"Global intensity override: {intensity}")

        cfg.ensure_output_dirs()

        # 3. Target Tests
        target_tests = tests or [
            name for name, wl in cfg.workloads.items() if wl.enabled
        ]
        if not target_tests:
            raise ValueError("No workloads selected to run.")

        # 4. Build Context
        context = self.build_context(
            cfg,
            target_tests,
            config_path=resolved,
            debug=debug,
            resume=resume,
            stop_file=stop_file,
            execution_mode=execution_mode,
        )
        return context

    def execute(
        self,
        context: RunContext,
        run_id: Optional[str],
        output_callback: Optional[Callable[[str, str], None]] = None,
        ui_adapter: UIAdapter | None = None,
    ) -> RunResult:
        """Execute benchmarks using remote hosts provisioned upstream."""
        if not context.config.remote_hosts:
            raise ValueError(
                "No remote hosts available. Provision nodes before running benchmarks."
            )

        stop_token = StopToken(stop_file=context.stop_file, enable_signals=False)
        formatter: AnsibleOutputFormatter | None = None
        callback = output_callback
        if callback is None:
            if context.debug:
                # In debug mode, print everything raw for troubleshooting
                def _debug_printer(text: str, end: str = ""):
                    print(text, end=end, flush=True)

                callback = _debug_printer
            else:
                formatter = AnsibleOutputFormatter()
                callback = formatter.process

        return self._run_remote(
            context,
            run_id,
            callback,
            formatter,
            ui_adapter,
            stop_token=stop_token,
        )

    def _run_remote(
        self,
        context: RunContext,
        run_id: Optional[str],
        output_callback: Callable[[str, str], None],
        formatter: AnsibleOutputFormatter | None,
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None = None,
    ) -> RunResult:
        """Execute a remote run using the controller with journal integration."""
        from ..controller import (
            BenchmarkController,
        )  # Runtime import to break circular dependency

        ui_stream_log_file: IO[str] | None = None
        stop_token = stop_token or StopToken(
            stop_file=context.stop_file, enable_signals=False
        )
        resume_requested = context.resume_from is not None or context.resume_latest
        journal, journal_path, dashboard, effective_run_id = (
            self._prepare_journal_and_dashboard(
                context, run_id, ui_adapter, ui_stream_log_file
            )
        )
        log_path = journal_path.parent / "run.log"
        log_file = log_path.open("a", encoding="utf-8")
        dashboard, ui_stream_log_path, ui_stream_log_file = self._enable_dashboard_log(
            dashboard, journal_path
        )

        # Fan-out Ansible output to both formatter and dashboard log stream.
        output_cb = output_callback
        if dashboard and output_callback is not None:
            last_refresh = 0.0

            def _dashboard_callback(text: str, end: str = ""):
                nonlocal last_refresh
                # If we're using the pretty formatter, let it drive both stdout and dashboard.
                if formatter and output_callback == formatter.process:
                    formatter.process(text, end=end, log_sink=dashboard.add_log)
                else:
                    output_callback(text, end=end)
                    dashboard.add_log(text)
                now = time.monotonic()
                if now - last_refresh > 0.25:
                    dashboard.refresh()
                    last_refresh = now

            output_cb = _dashboard_callback

        downstream = output_cb
        stop_announced = False

        def _announce_stop(
            msg: str = "Stop confirmed; initiating teardown and aborting the run.",
        ) -> None:
            nonlocal stop_announced
            if stop_announced:
                return
            stop_announced = True
            display_msg, log_msg = self._controller_stop_hint(msg)
            if ui_adapter:
                ui_adapter.show_warning(log_msg)
            elif dashboard:
                dashboard.add_log(display_msg)
                dashboard.refresh()
            else:
                print(log_msg)
            try:
                log_file.write(log_msg + "\n")
                log_file.flush()
            except Exception:
                pass

        stop_token._on_stop = _announce_stop  # type: ignore[attr-defined]

        sink = LogSink(journal, journal_path, log_path)
        recent_events: deque[tuple[str, str, int, str, str, str]] = deque()
        dedupe_limit = 200
        recent_set: set[tuple[str, str, int, str, str, str]] = set()

        if stop_token.should_stop():
            _announce_stop()

        # Short-circuit if nothing is pending.
        pending_exists = False
        hosts_for_pending = context.config.remote_hosts or []
        for host in hosts_for_pending:
            for test_name in context.target_tests:
                for rep in range(1, context.config.repetitions + 1):
                    if journal.should_run(host.name, test_name, rep):
                        pending_exists = True
                        break
                if pending_exists:
                    break
            if pending_exists:
                break
        if not pending_exists:
            msg = "All repetitions already completed; nothing to run."
            try:
                log_file.write(msg + "\n")
                log_file.flush()
            except Exception:
                pass
            sink.close()
            try:
                log_file.close()
            except Exception:
                pass
            if ui_stream_log_file:
                try:
                    ui_stream_log_file.close()
                except Exception:
                    pass
            if ui_adapter:
                ui_adapter.show_info(msg)
            stop_token.restore()
            return RunResult(
                context=context,
                summary=None,
                journal_path=journal_path,
                log_path=log_path,
                ui_log_path=ui_stream_log_path,
            )

        def _ingest_event(event: RunEvent, source: str = "unknown") -> None:
            # Include type and message in key to avoid deduping distinct log lines
            key = (
                event.host,
                event.workload,
                event.repetition,
                event.status,
                event.type,
                event.message,
            )
            if key in recent_set:
                return
            recent_events.append(key)
            recent_set.add(key)
            # Keep the dedupe window bounded
            if len(recent_events) > dedupe_limit:
                old = recent_events.popleft()
                if old in recent_set:
                    recent_set.remove(old)

            sink.emit(event)

            # Forward to controller for stop coordination
            # 'controller' is defined later in this scope but initialized before events flow
            if "controller" in locals() and controller:
                controller.on_event(event)

            if dashboard:
                dashboard.mark_event(source)
                label = f"run-{event.host}".replace(":", "-").replace(
                    " ", "-"
                ) + f"-{event.workload}".replace(":", "-").replace(" ", "-")
                text = f"• [{label}] {event.repetition}/{event.total_repetitions} {event.status}"
                if event.message:
                    text = f"{text} ({event.message})"
                dashboard.add_log(escape(text))
                dashboard.refresh()

        def _event_from_payload(data: Dict[str, Any]) -> RunEvent | None:
            required = {"host", "workload", "repetition", "status"}
            if not required.issubset(data.keys()):
                return None
            return RunEvent(
                run_id=journal.run_id,
                host=str(data.get("host", "")),
                workload=str(data.get("workload", "")),
                repetition=int(data.get("repetition") or 0),
                total_repetitions=int(
                    data.get("total_repetitions")
                    or data.get("total")
                    or context.config.repetitions
                ),
                status=str(data.get("status", "")),
                message=str(data.get("message") or ""),
                timestamp=time.time(),
                type=str(data.get("type", "status")),
                level=str(data.get("level", "INFO")),
            )

        def _handle_progress(line: str) -> None:
            info = self._parse_progress_line(line)
            if not info:
                return
            try:
                event = RunEvent(
                    run_id=journal.run_id,
                    host=info["host"],
                    workload=info["workload"],
                    repetition=info["rep"],
                    total_repetitions=info.get("total", context.config.repetitions),
                    status=info["status"],
                    message=info.get("message") or "",
                    timestamp=time.time(),
                )
                _ingest_event(event, source="stdout")
            except Exception:
                pass

        def _tee_output(text: str, end: str = "") -> None:
            fragment = text + (end if end else "\n")
            # Log everything for post-mortem debugging.
            try:
                log_file.write(fragment)
                log_file.flush()
            except Exception:
                pass
            for line in fragment.splitlines():
                _handle_progress(line)
            if downstream:
                downstream(text, end=end)

        output_cb = _tee_output

        controller = BenchmarkController(
            context.config,
            output_callback=output_cb,
            output_formatter=formatter if not context.debug else None,
            journal_refresh=dashboard.refresh if dashboard else None,
            stop_token=stop_token,
        )
        if formatter:
            formatter.host_label = ",".join(h.name for h in context.config.remote_hosts)
        event_tailer: JsonEventTailer | None = None
        event_log_path = getattr(
            getattr(controller, "executor", None), "event_log_path", None
        )
        if event_log_path:

            def _on_event_payload(data: Dict[str, Any]) -> None:
                event = _event_from_payload(data)
                if event:
                    _ingest_event(event, source="callback")

            event_tailer = JsonEventTailer(Path(event_log_path), _on_event_payload)
            # When callback stream is active, avoid duplicate progress from stdout parsing.
            if formatter:
                formatter.suppress_progress = True
            event_tailer.start()
        summary: RunExecutionSummary | None = None
        elapsed: float | None = None
        def _on_state_change(new_state: ControllerState, reason: str | None) -> None:
            line = f"Controller state: {new_state.value}"
            if reason:
                line = f"{line} ({reason})"
            try:
                log_file.write(line + "\n")
                log_file.flush()
                if ui_stream_log_file:
                    ui_stream_log_file.write(line + "\n")
                    ui_stream_log_file.flush()
            except Exception:
                pass
            if journal:
                try:
                    journal.metadata["controller_state"] = new_state.value
                    journal.save(journal_path)
                except Exception:
                    pass
            if dashboard:
                try:
                    dashboard.add_log(line)
                    dashboard.refresh()
                except Exception:
                    pass
            elif ui_adapter:
                try:
                    ui_adapter.show_info(line)
                except Exception:
                    pass

        runner = ControllerRunner(
            run_callable=lambda: controller.run(
                context.target_tests,
                run_id=effective_run_id,
                journal=journal,
                resume=resume_requested,
                journal_path=journal_path,
            ),
            stop_token=stop_token,
            on_state_change=_on_state_change,
        )
        try:
            with dashboard.live():
                start_ts = time.monotonic()
                runner.start()
                summary = runner.wait()
                elapsed = time.monotonic() - start_ts
                msg = f"Run {effective_run_id} completed in {elapsed:.1f}s"
                try:
                    log_file.write(msg + "\n")
                    log_file.flush()
                    if ui_stream_log_file:
                        ui_stream_log_file.write(msg + "\n")
                        ui_stream_log_file.flush()
                except Exception:
                    pass
                if ui_adapter:
                    ui_adapter.show_info(msg)
                elif dashboard:
                    dashboard.add_log(msg)
                else:
                    print(msg)
                if stop_token.should_stop():
                    _announce_stop()
                    self._fail_running_tasks(journal, reason="stopped")
                    journal.save(journal_path)
                    if summary is not None:
                        failed_teardowns = [
                            name
                            for name, res in summary.phases.items()
                            if name.startswith("teardown") and not res.success
                        ]
                        if failed_teardowns:
                            err = (
                                "Teardown failed ("
                                + ", ".join(failed_teardowns)
                                + "); remote workloads may still be running."
                            )
                            if ui_adapter:
                                ui_adapter.show_error(err)
                            elif dashboard:
                                dashboard.add_log(f"[red]{err}[/red]")
                                dashboard.refresh()
                            else:
                                print(err)
                            try:
                                log_file.write(err + "\n")
                                log_file.flush()
                            except Exception:
                                pass
                output_root = journal_path.parent
                hosts = (
                    [h.name for h in context.config.remote_hosts]
                    if context.config.remote_hosts
                    else ["localhost"]
                )
                if self._attach_system_info(
                    journal, output_root, hosts, dashboard, ui_adapter, log_file
                ):
                    journal.save(journal_path)
                if dashboard:
                    dashboard.refresh()
        finally:
            if event_tailer:
                event_tailer.stop()
            log_file.close()
            if ui_stream_log_file:
                ui_stream_log_file.close()

        sink.close()
        stop_token.restore()
        return RunResult(
            context=context,
            summary=summary,
            journal_path=journal_path,
            log_path=log_path,
            ui_log_path=ui_stream_log_path,
        )

    def _prepare_journal_and_dashboard(
        self,
        context: RunContext,
        run_id: Optional[str],
        ui_adapter: UIAdapter | None,
        ui_stream_log_file: IO[str] | None = None,
    ) -> tuple[RunJournal, Path, DashboardHandle, str]:
        """Load or create the run journal and optional dashboard."""
        resume_requested = context.resume_from is not None or context.resume_latest

        if resume_requested:
            original_remote_exec = (
                context.config.remote_execution if context.config else None
            )
            if context.resume_latest:
                journal_path = self._find_latest_journal(context.config)
                if journal_path is None:
                    raise ValueError("No previous run found to resume.")
            else:
                journal_path = (
                    context.config.output_dir / context.resume_from / "run_journal.json"
                )
            journal = RunJournal.load(journal_path)
            rehydrated = journal.rehydrate_config()
            # If the provided config does not match, prefer the journal's copy for resume.
            meta_hash = (journal.metadata or {}).get("config_hash")
            cfg_hash = _hash_config(context.config)
            if meta_hash and meta_hash != cfg_hash and rehydrated is not None:
                context.config = rehydrated
            elif context.config is None and rehydrated is not None:
                context.config = rehydrated
            # Preserve explicit remote execution overrides from the caller.
            if original_remote_exec and context.config:
                context.config.remote_execution.run_setup = (
                    original_remote_exec.run_setup
                )
                context.config.remote_execution.run_teardown = (
                    original_remote_exec.run_teardown
                )
                context.config.remote_execution.run_collect = (
                    original_remote_exec.run_collect
                )
            # Ensure new hosts/workloads are represented in the journal for resume.
            hosts = (
                context.config.remote_hosts
                if getattr(context.config, "remote_hosts", None)
                else [SimpleNamespace(name="localhost")]
            )
            for test_name in context.target_tests:
                if test_name not in context.config.workloads:
                    continue
                for host in hosts:
                    for rep in range(1, context.config.repetitions + 1):
                        if journal.get_task(host.name, test_name, rep):
                            continue
                        journal.add_task(
                            TaskState(
                                host=host.name, workload=test_name, repetition=rep
                            )
                        )
            if run_id and run_id != journal.run_id:
                raise ValueError(
                    f"Run ID mismatch: resume journal={journal.run_id}, cli={run_id}"
                )
            run_identifier = journal.run_id
        else:
            run_identifier = run_id or self._generate_run_id()
            journal_path = (
                context.config.output_dir / run_identifier / "run_journal.json"
            )
            journal = RunJournal.initialize(
                run_identifier, context.config, context.target_tests
            )

        # Persist the initial state so resume is possible even if execution aborts early
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal.save(journal_path)

        # Default stop file lives next to the journal.
        if context.stop_file is None:
            context.stop_file = journal_path.parent / "STOP"

        dashboard: DashboardHandle
        if ui_adapter:
            plan = self.get_run_plan(
                context.config,
                context.target_tests,
                execution_mode=context.execution_mode,
                registry=context.registry,
            )
            dashboard = ui_adapter.create_dashboard(plan, journal, ui_stream_log_file)
        else:
            dashboard = NoOpDashboardHandle()

        return journal, journal_path, dashboard, run_identifier

    def _build_journal_from_results(
        self,
        run_id: str,
        context: RunContext,
        host_name: str,
    ) -> RunJournal:
        """
        Construct a RunJournal from existing *_results.json artifacts when a journal is missing.
        """
        journal = RunJournal.initialize(run_id, context.config, context.target_tests)
        output_root = context.config.output_dir / run_id
        for test_name in context.target_tests:
            workload_dir = workload_output_dir(output_root, test_name)
            candidates = [
                workload_dir / f"{test_name}_results.json",
                output_root / f"{test_name}_results.json",
            ]
            results_file = next((path for path in candidates if path.exists()), None)
            if results_file is None:
                continue
            try:
                entries = json.loads(results_file.read_text())
            except Exception:
                continue
            for entry in entries or []:
                rep = entry.get("repetition")
                if rep is None:
                    continue
                task = journal.get_task(host_name, test_name, rep)
                if not task:
                    continue
                start_str = entry.get("start_time")
                end_str = entry.get("end_time")
                if start_str:
                    task.started_at = datetime.fromisoformat(start_str).timestamp()
                if end_str:
                    task.finished_at = datetime.fromisoformat(end_str).timestamp()
                duration = entry.get("duration_seconds")
                if duration is not None:
                    task.duration_seconds = float(duration)
                elif task.started_at is not None and task.finished_at is not None:
                    task.duration_seconds = max(0.0, task.finished_at - task.started_at)
                gen_result = entry.get("generator_result") or {}
                gen_error = gen_result.get("error")
                gen_rc = gen_result.get("returncode")
                if gen_error or (gen_rc not in (None, 0)):
                    journal.update_task(
                        host_name,
                        test_name,
                        rep,
                        RunStatus.FAILED,
                        action="container_run",
                        error=gen_error or f"returncode={gen_rc}",
                    )
                else:
                    journal.update_task(
                        host_name,
                        test_name,
                        rep,
                        RunStatus.COMPLETED,
                        action="container_run",
                    )
        return journal

    @staticmethod
    def _find_latest_journal(config: BenchmarkConfig) -> Path | None:
        """Return the most recent journal path if present."""
        root = config.output_dir
        if not root.exists():
            return None
        candidates = []
        for child in root.iterdir():
            candidate = child / "run_journal.json"
            if candidate.exists():
                candidates.append(candidate)
        if not candidates:
            return None
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a timestamped run id matching the controller's format."""
        return datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")

    def _parse_progress_line(self, line: str) -> dict[str, Any] | None:
        """Parse progress markers emitted by LocalRunner."""
        line = line.strip()
        data = _extract_lb_event_data(line, token=self._progress_token)
        if not data:
            return None
        required = {"host", "workload", "repetition", "status"}
        if not required.issubset(data.keys()):
            return None
        return {
            "host": data["host"],
            "workload": data["workload"],
            "rep": data.get("repetition", 0),
            "status": data["status"],
            "total": data.get("total_repetitions", 0),
            "message": data.get("message"),
            "type": data.get("type", "status"),
            "level": data.get("level", "INFO"),
        }

    @staticmethod
    def _fail_running_tasks(journal: RunJournal, reason: str = "stopped") -> None:
        """Mark any RUNNING tasks as FAILED with the given reason."""
        for task in journal.tasks.values():
            if task.status == RunStatus.RUNNING:
                task.status = RunStatus.FAILED
                task.current_action = reason
                task.error = reason

    # --- System info helpers ---

    def _system_info_candidates(self, base_dir: Path, host: str) -> list[Path]:
        """Return candidate paths for system info files for a given host."""
        return [
            base_dir / host / "system_info.json",
            base_dir / "system_info.json",
        ]

    def _summarize_system_info(self, path: Path) -> str | None:
        """Return a one-line summary for a system_info.json file."""
        try:
            data = json.loads(path.read_text())
        except Exception:
            return None
        os_info = data.get("os", {}) if isinstance(data, dict) else {}
        kernel = data.get("kernel", {}) if isinstance(data, dict) else {}
        cpu = data.get("cpu", {}) if isinstance(data, dict) else {}
        mem = data.get("memory", {}) if isinstance(data, dict) else {}
        disks = data.get("disks", []) if isinstance(data, dict) else []

        os_name = os_info.get("name") or os_info.get("id") or "Unknown OS"
        os_ver = os_info.get("version") or os_info.get("version_id") or ""
        kernel_rel = kernel.get("release") or kernel.get("version") or "kernel ?"

        model = (
            cpu.get("model_name")
            or cpu.get("model")
            or cpu.get("model_name:")
            or cpu.get("modelname")
            or cpu.get("architecture")
        )
        phys = cpu.get("physical_cpus") or cpu.get("cpu_cores") or "?"
        logi = cpu.get("logical_cpus") or cpu.get("cpus") or "?"

        def _to_gib(val: Any) -> str:
            try:
                return f"{int(val) / (1024**3):.1f}G"
            except Exception:
                return "?"

        ram_total = (
            mem.get("total_bytes") or mem.get("memtotal") or mem.get("memtotal:")
        )
        ram_str = _to_gib(ram_total) if ram_total is not None else "?"

        disk_summary = ""
        if isinstance(disks, list) and disks:
            first = disks[0]
            if isinstance(first, dict):
                name = first.get("name") or "disk"
                size = first.get("size_bytes") or first.get("size") or ""
                rota = first.get("rotational")
                kind = "SSD" if rota is False else "HDD" if rota is True else "disk"
                size_str = _to_gib(size) if size else ""
                disk_summary = f"{name} {kind} {size_str}".strip()

        parts = [
            f"OS: {os_name} {os_ver}".strip(),
            f"Kernel: {kernel_rel}",
            f"CPU: {model or '?'} ({phys}c/{logi}t)",
            f"RAM: {ram_str}",
        ]
        if disk_summary:
            parts.append(f"Disk: {disk_summary}")
        return " | ".join(parts)

    def _attach_system_info(
        self,
        journal: RunJournal,
        base_dir: Path,
        hosts: list[str],
        dashboard: DashboardHandle | None,
        ui_adapter: UIAdapter | None,
        log_file: IO[str] | None = None,
    ) -> bool:
        """Load system info summaries and surface them in metadata/logs. Returns True if any summary was added."""
        summaries: dict[str, str] = {}
        for host in hosts:
            summary = None
            for candidate in self._system_info_candidates(base_dir, host):
                if candidate.exists():
                    summary = self._summarize_system_info(candidate)
                    if summary:
                        break
            if summary:
                summaries[host] = summary
                journal.metadata.setdefault("system_info", {})[host] = summary
        if not summaries:
            return False
        for host, summary in summaries.items():
            line = f"{host}: {summary}"
            if dashboard:
                dashboard.add_log(f"[system] System info: {line}")
                dashboard.mark_event("system_info")
                dashboard.refresh()
            elif ui_adapter:
                ui_adapter.show_info(f"[system] {line}")
            else:
                print(f"[system] {line}")
            if log_file:
                try:
                    log_file.write(f"[system] System info: {line}\n")
                    log_file.flush()
                except Exception:
                    pass
        return True
