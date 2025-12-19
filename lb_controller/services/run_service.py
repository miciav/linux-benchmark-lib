"""Application-facing run orchestration helpers for the CLI."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import time
import re
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field, is_dataclass
import threading
import hashlib
import json
import queue
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
from lb_controller.controller_state import ControllerState, ControllerStateMachine
from lb_controller.interrupts import DoubleCtrlCStateMachine, SigintDoublePressHandler
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


@dataclass
class _RemoteSession:
    """Session-scoped state for a remote run."""

    journal: RunJournal
    journal_path: Path
    dashboard: DashboardHandle
    ui_stream_log_file: IO[str] | None
    ui_stream_log_path: Path | None
    log_path: Path
    log_file: IO[str]
    sink: LogSink
    stop_token: StopToken
    effective_run_id: str
    controller_state: ControllerStateMachine
    resume_requested: bool


@dataclass
class _EventPipeline:
    """Event/output wiring for a controller run."""

    output_cb: Callable[[str, str], None]
    announce_stop: Callable[[str], None]
    ingest_event: Callable[[RunEvent, str], None]
    event_from_payload: Callable[[Dict[str, Any]], RunEvent | None]
    sink: LogSink
    controller_ref: dict[str, BenchmarkController | None]


@dataclass
class _SignalContext:
    """State for SIGINT handling during controller runs."""

    events: queue.SimpleQueue[tuple[str, str | None]]
    state_machine: DoubleCtrlCStateMachine
    warning_timer: threading.Timer | None = None


@dataclass
class _EventDedupe:
    """Track recent events to avoid duplicate fan-out."""

    recent_events: deque[tuple[str, str, int, str, str, str]] = field(
        default_factory=deque
    )
    recent_set: set[tuple[str, str, int, str, str, str]] = field(default_factory=set)
    limit: int = 200

    def record(self, event: RunEvent) -> bool:
        """Return True if the event is new within the window."""
        key = (
            event.host,
            event.workload,
            event.repetition,
            event.status,
            event.type,
            event.message,
        )
        if key in self.recent_set:
            return False
        self.recent_events.append(key)
        self.recent_set.add(key)
        if len(self.recent_events) > self.limit:
            old = self.recent_events.popleft()
            self.recent_set.discard(old)
        return True


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

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        setter = getattr(self._inner, "set_warning", None)
        if callable(setter):
            setter(message, ttl)

    def clear_warning(self) -> None:
        clearer = getattr(self._inner, "clear_warning", None)
        if callable(clearer):
            clearer()

    def set_controller_state(self, state: str) -> None:
        setter = getattr(self._inner, "set_controller_state", None)
        if callable(setter):
            setter(state)


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
        mode = (execution_mode or "remote").lower()
        return [self._build_plan_item(cfg, name, mode, registry) for name in tests]

    def _build_plan_item(
        self,
        cfg: BenchmarkConfig,
        name: str,
        mode: str,
        registry: PluginRegistry,
    ) -> Dict[str, Any]:
        """Assemble a single plan item for display."""
        workload = cfg.workloads.get(name)
        item = {
            "name": name,
            "plugin": workload.plugin if workload else "unknown",
            "status": "[yellow]?[/yellow]",
            "intensity": workload.intensity if workload else "-",
            "details": "-",
            "repetitions": str(cfg.repetitions),
        }
        if workload is None:
            return item

        plugin = self._safe_get_plugin(registry, workload.plugin)
        if plugin is None:
            item["status"] = "[red]✗ (Missing)[/red]"
            return item

        config_obj, config_error = self._resolve_workload_config(workload, plugin)
        if config_error:
            item["details"] = f"[red]Config Error: {config_error}[/red]"
        else:
            item["details"] = self._format_plan_details(config_obj)

        item["status"] = self._status_for_mode(mode, default=item["status"])
        return item

    @staticmethod
    def _safe_get_plugin(registry: PluginRegistry, plugin_name: str):
        """Return plugin from registry or None on error."""
        try:
            return registry.get(plugin_name)
        except Exception:
            return None

    def _resolve_workload_config(
        self,
        workload: Any,
        plugin: Any,
    ) -> tuple[Any | None, str | None]:
        """Resolve config object from intensity presets or user options."""
        try:
            config_obj = None
            if workload.intensity and workload.intensity != "user_defined":
                try:
                    level = WorkloadIntensity(workload.intensity)
                    config_obj = plugin.get_preset_config(level)
                except ValueError:
                    pass
            if config_obj is None:
                if isinstance(workload.options, dict):
                    config_obj = plugin.config_cls(**workload.options)
                else:
                    config_obj = workload.options
            return config_obj, None
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)

    def _format_plan_details(self, config_obj: Any | None) -> str:
        """Return a concise description for a workload config."""
        if not config_obj:
            return "-"
        data = self._config_to_dict(config_obj)
        if not data:
            return str(config_obj)
        parts = self._summarize_config_fields(data)
        if not parts:
            return "-"
        return ", ".join(parts)

    @staticmethod
    def _config_to_dict(config_obj: Any) -> dict[str, Any]:
        """Convert config object to a dictionary when possible."""
        if isinstance(config_obj, dict):
            return config_obj
        try:
            from pydantic import BaseModel

            if isinstance(config_obj, BaseModel):
                return config_obj.model_dump()
        except Exception:
            pass
        try:
            if is_dataclass(config_obj):
                return asdict(config_obj)
        except Exception:
            pass
        return {}

    @staticmethod
    def _summarize_config_fields(data: dict[str, Any]) -> list[str]:
        """Format key config fields into a short, human-friendly list."""
        parts: list[str] = []
        duration = data.get("timeout") or data.get("time") or data.get("runtime")
        if duration:
            parts.append(f"Time: {duration}s")

        if data.get("cpu_workers"):
            parts.append(f"CPU: {data['cpu_workers']}")
        if "vm_bytes" in data:
            parts.append(f"VM: {data['vm_bytes']}")
        if "bs" in data:
            parts.append(f"BS: {data['bs']}")
        if data.get("count"):
            parts.append(f"Count: {data['count']}")
        if "parallel" in data:
            parts.append(f"Streams: {data['parallel']}")
        if "rw" in data:
            parts.append(f"Mode: {data['rw']}")
        if "iodepth" in data:
            parts.append(f"Depth: {data['iodepth']}")

        if len(parts) < 2:
            parts = [
                f"{key}={val}"
                for key, val in data.items()
                if val is not None and key not in ["extra_args"]
            ]
        return parts

    @staticmethod
    def _status_for_mode(mode: str, default: str = "[yellow]?[/yellow]") -> str:
        """Return a status tag based on execution mode."""
        mapping = {
            "docker": "[green]Docker (Ansible)[/green]",
            "multipass": "[green]Multipass[/green]",
            "remote": "[blue]Remote[/blue]",
        }
        return mapping.get(mode, default)

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
        cfg, resolved = self._load_or_default_config(
            config_service, config_path, ui_adapter, preloaded_config
        )
        self._apply_setup_overrides(
            cfg, setup, repetitions, intensity, ui_adapter, debug
        )
        target_tests = self._resolve_target_tests(cfg, tests)
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

    def _load_or_default_config(
        self,
        config_service: Any,
        config_path: Optional[Path],
        ui_adapter: UIAdapter | None,
        preloaded_config: BenchmarkConfig | None,
    ) -> tuple[BenchmarkConfig, Optional[Path]]:
        """Load config from disk or return a provided instance with UI feedback."""
        if preloaded_config is not None:
            return preloaded_config, config_path
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
        return cfg, resolved

    def _apply_setup_overrides(
        self,
        cfg: BenchmarkConfig,
        setup: bool,
        repetitions: Optional[int],
        intensity: Optional[str],
        ui_adapter: UIAdapter | None,
        debug: bool,
    ) -> None:
        """Apply CLI flags to config and ensure directories exist."""
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

    @staticmethod
    def _resolve_target_tests(
        cfg: BenchmarkConfig, tests: Optional[List[str]]
    ) -> List[str]:
        """Determine which workloads to run, raising if none are enabled/selected."""
        target_tests = tests or [
            name for name, wl in cfg.workloads.items() if wl.enabled
        ]
        if not target_tests:
            raise ValueError("No workloads selected to run.")
        return target_tests

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

        session = self._prepare_remote_session(context, run_id, ui_adapter, stop_token)

        if not session.stop_token.should_stop() and not self._pending_exists(
            context, session.journal
        ):
            return self._short_circuit_empty_run(context, session, ui_adapter)

        pipeline = self._build_event_pipeline(
            context, session, formatter, output_callback, ui_adapter
        )

        controller = BenchmarkController(
            context.config,
            output_callback=pipeline.output_cb,
            output_formatter=formatter if not context.debug else None,
            journal_refresh=session.dashboard.refresh if session.dashboard else None,
            stop_token=session.stop_token,
            state_machine=session.controller_state,
        )
        pipeline.controller_ref["controller"] = controller
        if formatter:
            formatter.host_label = ",".join(h.name for h in context.config.remote_hosts)

        tailer = self._maybe_start_event_tailer(
            controller, pipeline.event_from_payload, pipeline.ingest_event, formatter
        )

        summary = self._run_controller_loop(
            controller=controller,
            context=context,
            session=session,
            pipeline=pipeline,
            ui_adapter=ui_adapter,
        )

        if tailer:
            tailer.stop()
        session.sink.close()
        session.stop_token.restore()
        return RunResult(
            context=context,
            summary=summary,
            journal_path=session.journal_path,
            log_path=session.log_path,
            ui_log_path=session.ui_stream_log_path,
        )

    def _prepare_remote_session(
        self,
        context: RunContext,
        run_id: Optional[str],
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None,
    ) -> _RemoteSession:
        """Initialize journal, dashboard, log files, and session state."""
        ui_stream_log_file: IO[str] | None = None
        stop = stop_token or StopToken(
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
        sink = LogSink(journal, journal_path, log_path)
        return _RemoteSession(
            journal=journal,
            journal_path=journal_path,
            dashboard=dashboard,
            ui_stream_log_file=ui_stream_log_file,
            ui_stream_log_path=ui_stream_log_path,
            log_path=log_path,
            log_file=log_file,
            sink=sink,
            stop_token=stop,
            effective_run_id=effective_run_id,
            controller_state=ControllerStateMachine(),
            resume_requested=resume_requested,
        )

    def _pending_exists(self, context: RunContext, journal: RunJournal) -> bool:
        """Return True if any repetition still needs to run."""
        hosts = context.config.remote_hosts or []
        for host in hosts:
            for test_name in context.target_tests:
                for rep in range(1, context.config.repetitions + 1):
                    if journal.should_run(host.name, test_name, rep):
                        return True
        return False

    def _short_circuit_empty_run(
        self, context: RunContext, session: _RemoteSession, ui_adapter: UIAdapter | None
    ) -> RunResult:
        """Handle resume cases where nothing remains to run."""
        msg = "All repetitions already completed; nothing to run."
        try:
            session.log_file.write(msg + "\n")
            session.log_file.flush()
        except Exception:
            pass
        session.sink.close()
        try:
            session.log_file.close()
        except Exception:
            pass
        if session.ui_stream_log_file:
            try:
                session.ui_stream_log_file.close()
            except Exception:
                pass
        if ui_adapter:
            ui_adapter.show_info(msg)
        session.stop_token.restore()
        return RunResult(
            context=context,
            summary=None,
            journal_path=session.journal_path,
            log_path=session.log_path,
            ui_log_path=session.ui_stream_log_path,
        )

    def _build_event_pipeline(
        self,
        context: RunContext,
        session: _RemoteSession,
        formatter: AnsibleOutputFormatter | None,
        output_callback: Callable[[str, str], None],
        ui_adapter: UIAdapter | None,
    ) -> _EventPipeline:
        """Wire output handlers, dedupe, and dashboard logging."""
        dashboard = session.dashboard
        output_cb = self._pipeline_output_callback(
            dashboard=dashboard, formatter=formatter, output_callback=output_callback
        )
        announce_stop = self._announce_stop_factory(session, ui_adapter)
        session.stop_token._on_stop = announce_stop  # type: ignore[attr-defined]

        controller_ref: dict[str, BenchmarkController | None] = {"controller": None}
        dedupe = _EventDedupe()
        ingest_event = self._make_ingest_event(
            session=session,
            dashboard=dashboard,
            controller_ref=controller_ref,
            dedupe=dedupe,
        )
        event_from_payload = lambda data: self._event_from_payload_data(
            data, session, context
        )
        progress_handler = self._make_progress_handler(
            session=session,
            context=context,
            ingest_event=ingest_event,
        )
        output_with_progress = self._make_output_tee(
            session=session,
            downstream=output_cb,
            progress_handler=progress_handler,
        )

        if session.stop_token.should_stop():
            announce_stop()

        return _EventPipeline(
            output_cb=output_with_progress,
            announce_stop=announce_stop,
            ingest_event=ingest_event,
            event_from_payload=event_from_payload,
            sink=session.sink,
            controller_ref=controller_ref,
        )

    def _pipeline_output_callback(
        self,
        dashboard: DashboardHandle | None,
        formatter: AnsibleOutputFormatter | None,
        output_callback: Callable[[str, str], None],
    ) -> Callable[[str, str], None]:
        """Fan-out formatter output to dashboard when available."""
        if not dashboard or output_callback is None:
            return output_callback

        last_refresh = {"ts": 0.0}

        def _dashboard_callback(text: str, end: str = ""):
            if formatter and output_callback == formatter.process:
                formatter.process(text, end=end, log_sink=dashboard.add_log)
            else:
                output_callback(text, end=end)
                dashboard.add_log(text)
            now = time.monotonic()
            if now - last_refresh["ts"] > 0.25:
                dashboard.refresh()
                last_refresh["ts"] = now

        return _dashboard_callback

    def _announce_stop_factory(
        self, session: _RemoteSession, ui_adapter: UIAdapter | None
    ) -> Callable[[str], None]:
        """Create a stop announcer that logs to UI/dashboard."""
        stop_announced = {"value": False}

        def _announce_stop(
            msg: str = "Stop confirmed; initiating teardown and aborting the run.",
        ) -> None:
            if stop_announced["value"]:
                return
            stop_announced["value"] = True
            try:
                session.controller_state.transition(
                    ControllerState.STOP_ARMED, reason=msg
                )
            except Exception:
                pass
            display_msg, log_msg = self._controller_stop_hint(msg)
            if ui_adapter:
                ui_adapter.show_warning(log_msg)
            elif session.dashboard:
                session.dashboard.add_log(display_msg)
                session.dashboard.refresh()
            else:
                print(log_msg)
            try:
                session.log_file.write(log_msg + "\n")
                session.log_file.flush()
                if session.ui_stream_log_file:
                    session.ui_stream_log_file.write(log_msg + "\n")
                    session.ui_stream_log_file.flush()
            except Exception:
                pass

        return _announce_stop

    def _make_ingest_event(
        self,
        session: _RemoteSession,
        dashboard: DashboardHandle | None,
        controller_ref: dict[str, BenchmarkController | None],
        dedupe: _EventDedupe,
    ) -> Callable[[RunEvent, str], None]:
        """Return an ingest function that updates journal, controller, and dashboard."""

        def _ingest(event: RunEvent, source: str = "unknown") -> None:
            if not dedupe.record(event):
                return
            session.sink.emit(event)
            controller = controller_ref.get("controller")
            if controller:
                controller.on_event(event)
            self._mirror_event_to_dashboard(event, dashboard, source)

        return _ingest

    @staticmethod
    def _mirror_event_to_dashboard(
        event: RunEvent, dashboard: DashboardHandle | None, source: str
    ) -> None:
        if not dashboard:
            return
        dashboard.mark_event(source)
        label = f"run-{event.host}".replace(":", "-").replace(
            " ", "-"
        ) + f"-{event.workload}".replace(":", "-").replace(" ", "-")
        text = (
            f"• [{label}] {event.repetition}/{event.total_repetitions} {event.status}"
        )
        if event.message:
            text = f"{text} ({event.message})"
        dashboard.add_log(escape(text))
        dashboard.refresh()

    @staticmethod
    def _event_from_payload_data(
        data: Dict[str, Any], session: _RemoteSession, context: RunContext
    ) -> RunEvent | None:
        required = {"host", "workload", "repetition", "status"}
        if not required.issubset(data.keys()):
            return None
        return RunEvent(
            run_id=session.journal.run_id,
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

    def _make_progress_handler(
        self,
        session: _RemoteSession,
        context: RunContext,
        ingest_event: Callable[[RunEvent, str], None],
    ) -> Callable[[str], None]:
        """Return a handler that converts stdout markers into RunEvents."""

        def _handle_progress(line: str) -> None:
            info = self._parse_progress_line(line)
            if not info:
                return
            try:
                event = RunEvent(
                    run_id=session.journal.run_id,
                    host=info["host"],
                    workload=info["workload"],
                    repetition=info["rep"],
                    total_repetitions=info.get("total", context.config.repetitions),
                    status=info["status"],
                    message=info.get("message") or "",
                    timestamp=time.time(),
                )
                ingest_event(event, source="stdout")
            except Exception:
                pass

        return _handle_progress

    def _make_output_tee(
        self,
        session: _RemoteSession,
        downstream: Callable[[str, str], None] | None,
        progress_handler: Callable[[str], None],
    ) -> Callable[[str, str], None]:
        """Return an output callback that logs, parses progress, and tees downstream."""

        def _tee_output(text: str, end: str = "") -> None:
            fragment = text + (end if end else "\n")
            try:
                session.log_file.write(fragment)
                session.log_file.flush()
            except Exception:
                pass
            for line in fragment.splitlines():
                progress_handler(line)
            if downstream:
                downstream(text, end=end)

        return _tee_output

    def _maybe_start_event_tailer(
        self,
        controller: BenchmarkController,
        event_from_payload: Callable[[Dict[str, Any]], RunEvent | None],
        ingest_event: Callable[[RunEvent, str], None],
        formatter: AnsibleOutputFormatter | None,
    ) -> JsonEventTailer | None:
        """Start a callback tailer when the controller provides an event log path."""
        event_log_path = getattr(
            getattr(controller, "executor", None), "event_log_path", None
        )
        if not event_log_path:
            return None

        def _on_event_payload(data: Dict[str, Any]) -> None:
            event = event_from_payload(data)
            if event:
                ingest_event(event, source="callback")

        event_tailer = JsonEventTailer(Path(event_log_path), _on_event_payload)
        if formatter:
            formatter.suppress_progress = True
        event_tailer.start()
        return event_tailer

    def _run_controller_loop(
        self,
        controller: BenchmarkController,
        context: RunContext,
        session: _RemoteSession,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None,
    ) -> RunExecutionSummary | None:
        """Drive the controller runner with signal handling and logging."""
        runner = self._build_controller_runner(controller, context, session, ui_adapter)
        signals = self._build_signal_context(session, ui_adapter)
        try:
            summary, elapsed = self._drive_runner(
                runner, session, signals, pipeline, ui_adapter=ui_adapter
            )
            self._handle_run_completion(
                summary=summary,
                elapsed=elapsed,
                context=context,
                session=session,
                pipeline=pipeline,
                ui_adapter=ui_adapter,
            )
        finally:
            self._cleanup_signal_context(signals)
            try:
                session.log_file.close()
            except Exception:
                pass
            if session.ui_stream_log_file:
                try:
                    session.ui_stream_log_file.close()
                except Exception:
                    pass
        return summary

    def _build_controller_runner(
        self,
        controller: BenchmarkController,
        context: RunContext,
        session: _RemoteSession,
        ui_adapter: UIAdapter | None,
    ) -> ControllerRunner:
        """Create the controller runner with state-change callbacks."""
        return ControllerRunner(
            run_callable=lambda: controller.run(
                context.target_tests,
                run_id=session.effective_run_id,
                journal=session.journal,
                resume=session.resume_requested,
                journal_path=session.journal_path,
            ),
            stop_token=session.stop_token,
            on_state_change=lambda new, reason: self._on_controller_state_change(
                new, reason, session, ui_adapter
            ),
            state_machine=session.controller_state,
        )

    def _build_signal_context(
        self, session: _RemoteSession, ui_adapter: UIAdapter | None
    ) -> _SignalContext:
        """Initialize SIGINT handling primitives for the run loop."""
        ctx = _SignalContext(
            events=queue.SimpleQueue(), state_machine=DoubleCtrlCStateMachine()
        )
        ctx.state_machine.reset_arm()
        return ctx

    def _drive_runner(
        self,
        runner: ControllerRunner,
        session: _RemoteSession,
        signals: _SignalContext,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None = None,
    ) -> tuple[RunExecutionSummary | None, float]:
        """Run controller loop, honoring double-SIGINT semantics."""

        def _run_active() -> bool:
            return not session.controller_state.is_terminal()

        start_ts = time.monotonic()
        summary: RunExecutionSummary | None = None

        with (
            session.dashboard.live(),
            SigintDoublePressHandler(
                state_machine=signals.state_machine,
                run_active=_run_active,
                on_first_sigint=lambda: signals.events.put(("warn", None)),
                on_confirmed_sigint=lambda: signals.events.put(
                    ("stop", "User requested stop")
                ),
            ),
        ):
            runner.start()
            while True:
                self._drain_ctrlc_events(
                    runner, session, signals, pipeline, ui_adapter=ui_adapter
                )
                candidate = runner.wait(timeout=0.2)
                if candidate is not None:
                    summary = candidate
                    break
        elapsed = time.monotonic() - start_ts
        return summary, elapsed

    def _drain_ctrlc_events(
        self,
        runner: ControllerRunner,
        session: _RemoteSession,
        signals: _SignalContext,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None = None,
    ) -> None:
        """Process pending SIGINT events."""
        while True:
            try:
                kind, reason = signals.events.get_nowait()
            except queue.Empty:
                return
            if kind == "warn":
                self._log_arm_warning(session, signals, ui_adapter)
            elif kind == "stop":
                runner.arm_stop(reason or "User requested stop")
                pipeline.announce_stop()

    def _log_arm_warning(
        self,
        session: _RemoteSession,
        signals: _SignalContext,
        ui_adapter: UIAdapter | None,
    ) -> None:
        """Emit and schedule clearance for the first Ctrl+C warning."""
        msg = "Press Ctrl+C again to stop the execution"
        self._emit_warning(
            msg,
            dashboard=session.dashboard,
            ui_adapter=ui_adapter,
            log_file=session.log_file,
            ui_stream_log_file=session.ui_stream_log_file,
            ttl=10.0,
        )
        if signals.warning_timer and signals.warning_timer.is_alive():
            signals.warning_timer.cancel()

        def _clear_warning() -> None:
            signals.state_machine.reset_arm()
            if session.dashboard and hasattr(session.dashboard, "clear_warning"):
                try:
                    session.dashboard.clear_warning()
                    session.dashboard.refresh()
                except Exception:
                    pass

        timer = threading.Timer(10.0, _clear_warning)
        timer.daemon = True
        timer.start()
        signals.warning_timer = timer

    def _handle_run_completion(
        self,
        summary: RunExecutionSummary | None,
        elapsed: float,
        context: RunContext,
        session: _RemoteSession,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None,
    ) -> None:
        """Finalize run, surface results, and attach metadata."""
        self._log_completion(elapsed, session, ui_adapter)
        if session.stop_token.should_stop():
            self._on_stop_requested(summary, session, pipeline, ui_adapter)
        self._attach_and_log_system_info(context, session, ui_adapter)

    def _log_completion(
        self,
        elapsed: float,
        session: _RemoteSession,
        ui_adapter: UIAdapter | None,
    ) -> None:
        msg = f"Run {session.effective_run_id} completed in {elapsed:.1f}s"
        try:
            session.log_file.write(msg + "\n")
            session.log_file.flush()
            if session.ui_stream_log_file:
                session.ui_stream_log_file.write(msg + "\n")
                session.ui_stream_log_file.flush()
        except Exception:
            pass
        if ui_adapter:
            ui_adapter.show_info(msg)
        elif session.dashboard:
            session.dashboard.add_log(msg)
        else:
            print(msg)

    def _on_stop_requested(
        self,
        summary: RunExecutionSummary | None,
        session: _RemoteSession,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None,
    ) -> None:
        """Handle teardown when a stop was requested."""
        pipeline.announce_stop()
        self._fail_running_tasks(session.journal, reason="stopped")
        session.journal.save(session.journal_path)
        if summary is None:
            return
        failed_teardowns = [
            name
            for name, res in summary.phases.items()
            if name.startswith("teardown") and not res.success
        ]
        if not failed_teardowns:
            return
        err = (
            "Teardown failed ("
            + ", ".join(failed_teardowns)
            + "); remote workloads may still be running."
        )
        if ui_adapter:
            ui_adapter.show_error(err)
        elif session.dashboard:
            session.dashboard.add_log(f"[red]{err}[/red]")
            session.dashboard.refresh()
        else:
            print(err)
        try:
            session.log_file.write(err + "\n")
            session.log_file.flush()
        except Exception:
            pass

    def _attach_and_log_system_info(
        self,
        context: RunContext,
        session: _RemoteSession,
        ui_adapter: UIAdapter | None,
    ) -> None:
        """Attach system info summaries to journal and UI if present."""
        output_root = session.journal_path.parent
        hosts = (
            [h.name for h in context.config.remote_hosts]
            if context.config.remote_hosts
            else ["localhost"]
        )
        if self._attach_system_info(
            session.journal,
            output_root,
            hosts,
            session.dashboard,
            ui_adapter,
            session.log_file,
        ):
            session.journal.save(session.journal_path)
        if session.dashboard:
            session.dashboard.refresh()

    @staticmethod
    def _cleanup_signal_context(signals: _SignalContext) -> None:
        """Ensure timers are cancelled after the run."""
        if signals.warning_timer and signals.warning_timer.is_alive():
            signals.warning_timer.cancel()

    def _on_controller_state_change(
        self,
        new_state: ControllerState,
        reason: str | None,
        session: _RemoteSession,
        ui_adapter: UIAdapter | None,
    ) -> None:
        """Handle controller state transitions consistently."""
        line = f"Controller state: {new_state.value}"
        if reason:
            line = f"{line} ({reason})"
        try:
            session.log_file.write(line + "\n")
            session.log_file.flush()
            if session.ui_stream_log_file:
                session.ui_stream_log_file.write(line + "\n")
                session.ui_stream_log_file.flush()
        except Exception:
            pass
        if session.journal:
            try:
                session.journal.metadata["controller_state"] = new_state.value
                session.journal.save(session.journal_path)
            except Exception:
                pass
        if session.dashboard:
            try:
                if hasattr(session.dashboard, "set_controller_state"):
                    session.dashboard.set_controller_state(new_state.value)
                session.dashboard.refresh()
            except Exception:
                pass
        elif ui_adapter:
            try:
                ui_adapter.show_info(line)
            except Exception:
                pass

    def _emit_warning(
        self,
        message: str,
        *,
        dashboard: DashboardHandle | None,
        ui_adapter: UIAdapter | None,
        log_file: IO[str],
        ui_stream_log_file: IO[str] | None,
        ttl: float = 10.0,
    ) -> None:
        """Send a warning to UI, dashboard, and logs in a consistent way."""
        display = f"[yellow]{message}[/yellow]"
        if ui_adapter:
            try:
                ui_adapter.show_warning(message)
            except Exception:
                pass
        if dashboard:
            try:
                if hasattr(dashboard, "set_warning"):
                    dashboard.set_warning(message, ttl=ttl)
            except Exception:
                pass
            try:
                dashboard.refresh()
            except Exception:
                pass
        else:
            # Fallback to stdout if no UI/dash
            print(message)
        try:
            log_file.write(message + "\n")
            log_file.flush()
            if ui_stream_log_file:
                ui_stream_log_file.write(message + "\n")
                ui_stream_log_file.flush()
        except Exception:
            pass

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
            journal, journal_path, run_identifier = self._load_resume_journal(
                context, run_id
            )
        else:
            journal, journal_path, run_identifier = self._initialize_new_journal(
                context, run_id
            )

        # Persist the initial state so resume is possible even if execution aborts early
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal.save(journal_path)

        # Default stop file lives next to the journal.
        if context.stop_file is None:
            context.stop_file = journal_path.parent / "STOP"

        dashboard = self._create_dashboard(
            context, ui_adapter, journal, ui_stream_log_file
        )

        return journal, journal_path, dashboard, run_identifier

    def _load_resume_journal(
        self, context: RunContext, run_id: Optional[str]
    ) -> tuple[RunJournal, Path, str]:
        """Load an existing journal and reconcile configuration for resume."""
        journal_path = self._resolve_resume_path(context)
        journal = RunJournal.load(journal_path)
        self._rehydrate_resume_config(context, journal)
        self._ensure_resume_tasks(context, journal)
        if run_id and run_id != journal.run_id:
            raise ValueError(
                f"Run ID mismatch: resume journal={journal.run_id}, cli={run_id}"
            )
        return journal, journal_path, journal.run_id

    def _resolve_resume_path(self, context: RunContext) -> Path:
        """Locate the correct journal path for resume."""
        if context.resume_latest:
            journal_path = self._find_latest_journal(context.config)
            if journal_path is None:
                raise ValueError("No previous run found to resume.")
            return journal_path
        return context.config.output_dir / context.resume_from / "run_journal.json"

    def _rehydrate_resume_config(
        self, context: RunContext, journal: RunJournal
    ) -> None:
        """Restore config from journal when resuming, preserving explicit overrides."""
        original_remote_exec = (
            context.config.remote_execution if context.config else None
        )
        rehydrated = journal.rehydrate_config()
        meta_hash = (journal.metadata or {}).get("config_hash")
        cfg_hash = _hash_config(context.config)
        if meta_hash and meta_hash != cfg_hash and rehydrated is not None:
            context.config = rehydrated
        elif context.config is None and rehydrated is not None:
            context.config = rehydrated
        if original_remote_exec and context.config:
            context.config.remote_execution.run_setup = original_remote_exec.run_setup
            context.config.remote_execution.run_teardown = (
                original_remote_exec.run_teardown
            )
            context.config.remote_execution.run_collect = (
                original_remote_exec.run_collect
            )

    def _ensure_resume_tasks(self, context: RunContext, journal: RunJournal) -> None:
        """Add any missing tasks to the resume journal for new hosts/workloads."""
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
                        TaskState(host=host.name, workload=test_name, repetition=rep)
                    )

    def _initialize_new_journal(
        self, context: RunContext, run_id: Optional[str]
    ) -> tuple[RunJournal, Path, str]:
        """Create a fresh journal for a new run."""
        run_identifier = run_id or self._generate_run_id()
        journal_path = context.config.output_dir / run_identifier / "run_journal.json"
        journal = RunJournal.initialize(
            run_identifier, context.config, context.target_tests
        )
        return journal, journal_path, run_identifier

    def _create_dashboard(
        self,
        context: RunContext,
        ui_adapter: UIAdapter | None,
        journal: RunJournal,
        ui_stream_log_file: IO[str] | None,
    ) -> DashboardHandle:
        """Build a dashboard handle or a no-op substitute."""
        if not ui_adapter:
            return NoOpDashboardHandle()
        plan = self.get_run_plan(
            context.config,
            context.target_tests,
            execution_mode=context.execution_mode,
            registry=context.registry,
        )
        return ui_adapter.create_dashboard(plan, journal, ui_stream_log_file)

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
            results_file = self._find_results_file(output_root, test_name)
            if not results_file:
                continue
            entries = self._load_results_entries(results_file)
            for entry in entries:
                self._apply_result_entry(journal, host_name, test_name, entry)
        return journal

    @staticmethod
    def _find_results_file(output_root: Path, test_name: str) -> Path | None:
        """Locate results JSON for a given workload."""
        workload_dir = workload_output_dir(output_root, test_name)
        candidates = [
            workload_dir / f"{test_name}_results.json",
            output_root / f"{test_name}_results.json",
        ]
        return next((path for path in candidates if path.exists()), None)

    @staticmethod
    def _load_results_entries(path: Path) -> list[dict[str, Any]]:
        """Load result entries from disk, tolerating errors."""
        try:
            loaded = json.loads(path.read_text())
            return loaded or []
        except Exception:
            return []

    def _apply_result_entry(
        self,
        journal: RunJournal,
        host_name: str,
        test_name: str,
        entry: dict[str, Any],
    ) -> None:
        """Update journal tasks from a single results entry."""
        rep = entry.get("repetition")
        if rep is None:
            return
        task = journal.get_task(host_name, test_name, rep)
        if not task:
            return
        self._populate_task_times(task, entry)
        self._update_task_status_from_result(journal, host_name, test_name, rep, entry)

    @staticmethod
    def _populate_task_times(task: TaskState, entry: dict[str, Any]) -> None:
        """Fill in start/end/duration fields from results."""
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

    def _update_task_status_from_result(
        self,
        journal: RunJournal,
        host_name: str,
        test_name: str,
        rep: int,
        entry: dict[str, Any],
    ) -> None:
        """Set task status based on generator result fields."""
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
            return
        journal.update_task(
            host_name,
            test_name,
            rep,
            RunStatus.COMPLETED,
            action="container_run",
        )

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
        data = self._load_json(path)
        if not isinstance(data, dict):
            return None
        os_part = self._format_os_summary(data)
        cpu_part = self._format_cpu_summary(data)
        mem_part = self._format_memory_summary(data)
        disk_part = self._format_disk_summary(data)
        parts = [os_part, cpu_part, mem_part, disk_part]
        parts = [part for part in parts if part]
        return " | ".join(parts) if parts else None

    @staticmethod
    def _load_json(path: Path) -> Any:
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    @staticmethod
    def _format_os_summary(data: dict[str, Any]) -> str:
        os_info = data.get("os", {}) if isinstance(data, dict) else {}
        kernel = data.get("kernel", {}) if isinstance(data, dict) else {}
        os_name = os_info.get("name") or os_info.get("id") or "Unknown OS"
        os_ver = os_info.get("version") or os_info.get("version_id") or ""
        kernel_rel = kernel.get("release") or kernel.get("version") or "kernel ?"
        return f"OS: {os_name} {os_ver}".strip() + f" | Kernel: {kernel_rel}"

    @staticmethod
    def _format_cpu_summary(data: dict[str, Any]) -> str:
        cpu = data.get("cpu", {}) if isinstance(data, dict) else {}
        model = (
            cpu.get("model_name")
            or cpu.get("model")
            or cpu.get("model_name:")
            or cpu.get("modelname")
            or cpu.get("architecture")
        )
        phys = cpu.get("physical_cpus") or cpu.get("cpu_cores") or "?"
        logi = cpu.get("logical_cpus") or cpu.get("cpus") or "?"
        return f"CPU: {model or '?'} ({phys}c/{logi}t)"

    def _format_memory_summary(self, data: dict[str, Any]) -> str:
        mem = data.get("memory", {}) if isinstance(data, dict) else {}
        ram_total = (
            mem.get("total_bytes") or mem.get("memtotal") or mem.get("memtotal:")
        )
        ram_str = self._to_gib(ram_total) if ram_total is not None else "?"
        return f"RAM: {ram_str}"

    def _format_disk_summary(self, data: dict[str, Any]) -> str | None:
        disks = data.get("disks", []) if isinstance(data, dict) else []
        if not isinstance(disks, list) or not disks:
            return None
        first = disks[0]
        if not isinstance(first, dict):
            return None
        name = first.get("name") or "disk"
        size = first.get("size_bytes") or first.get("size") or ""
        rota = first.get("rotational")
        kind = "SSD" if rota is False else "HDD" if rota is True else "disk"
        size_str = self._to_gib(size) if size else ""
        disk_summary = f"{name} {kind} {size_str}".strip()
        return f"Disk: {disk_summary}" if disk_summary else None

    @staticmethod
    def _to_gib(val: Any) -> str:
        try:
            return f"{int(val) / (1024**3):.1f}G"
        except Exception:
            return "?"

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
        summaries = self._collect_system_info(hosts, base_dir, journal)
        if not summaries:
            return False
        self._log_system_info(summaries, dashboard, ui_adapter, log_file)
        return True

    def _collect_system_info(
        self, hosts: list[str], base_dir: Path, journal: RunJournal
    ) -> dict[str, str]:
        """Gather system info summaries for each host and update journal metadata."""
        summaries: dict[str, str] = {}
        for host in hosts:
            summary = self._find_system_summary(base_dir, host)
            if summary:
                summaries[host] = summary
                journal.metadata.setdefault("system_info", {})[host] = summary
        return summaries

    def _find_system_summary(self, base_dir: Path, host: str) -> str | None:
        """Return the first available system info summary for a host."""
        for candidate in self._system_info_candidates(base_dir, host):
            if candidate.exists():
                summary = self._summarize_system_info(candidate)
                if summary:
                    return summary
        return None

    @staticmethod
    def _log_system_info(
        summaries: dict[str, str],
        dashboard: DashboardHandle | None,
        ui_adapter: UIAdapter | None,
        log_file: IO[str] | None,
    ) -> None:
        """Emit system info summaries to available sinks."""
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
