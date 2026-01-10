"""Application-facing run orchestration helpers for the CLI."""

from __future__ import annotations

import logging
import platform
import time
import threading
import queue
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Callable, Dict, List, Optional

from lb_controller.api import BenchmarkConfig, PlatformConfig, StopToken
from lb_plugins.api import PluginRegistry, apply_plugin_assets, create_registry
from lb_runner.api import RunEvent
from lb_controller.api import (
    BenchmarkController,
    apply_playbook_defaults,
)
from lb_app.ui_interfaces import UIAdapter, DashboardHandle

if TYPE_CHECKING:
    from lb_controller.api import BenchmarkController, RunExecutionSummary
from lb_app.services.run_pipeline import (
    event_from_payload_data,
    make_ingest_event,
    make_output_tee,
    make_progress_handler,
    parse_progress_line,
    pipeline_output_callback,
)
from lb_app.services.run_output import (  # noqa: F401
    AnsibleOutputFormatter,
    _extract_lb_event_data,
)
from lb_app.services.run_plan import build_run_plan
from lb_app.services.remote_run_coordinator import RemoteRunCoordinator
from lb_app.services.run_types import (
    RunContext,
    RunResult,
    _RemoteSession,
    _EventPipeline,
    _EventDedupe,
)
from lb_app.services.run_logging import announce_stop_factory
from lb_app.services.execution_loop import RunExecutionLoop
from lb_app.services.session_manager import SessionManager
from lb_common.api import (
    JsonlLogFormatter,
    attach_jsonl_handler,
    attach_loki_handler,
)


class RunService:
    """Coordinate benchmark execution for CLI commands."""

    def __init__(self, registry_factory: Callable[[], PluginRegistry]):
        self._registry_factory = registry_factory
        self._progress_token = "LB_EVENT"
        self._execution_loop = RunExecutionLoop()
        self._session_manager = SessionManager(registry_factory)

    def get_run_plan(
        self,
        cfg: BenchmarkConfig,
        tests: List[str],
        execution_mode: str = "remote",
        registry: PluginRegistry | None = None,
        platform_config: PlatformConfig | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Build a detailed plan for the workloads to be run.

        Returns a list of dictionaries containing status, intensity, details, etc.
        """
        registry = registry or self._registry_factory()
        return build_run_plan(
            cfg,
            tests,
            execution_mode=execution_mode,
            registry=registry,
            platform_config=platform_config,
        )

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
        node_count: int | None = None,
    ) -> RunContext:
        """Compute the run context and registry."""
        registry = self._registry_factory()
        target_tests = tests or list(cfg.workloads.keys())
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
            node_count=node_count,
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
        node_count: int | None = None,
        preloaded_config: BenchmarkConfig | None = None,
    ) -> RunContext:
        """
        Orchestrate the creation of a RunContext from raw inputs.

        This method consolidates configuration loading, overrides, and context building.
        """
        cfg, resolved = self._load_or_default_config(
            config_service, config_path, ui_adapter, preloaded_config
        )
        platform_config, _, _ = config_service.load_platform_config()
        self._apply_platform_defaults(cfg, platform_config)
        apply_playbook_defaults(cfg)
        self._apply_setup_overrides(
            cfg, setup, repetitions, intensity, ui_adapter, debug
        )
        target_tests = self._resolve_target_tests(
            cfg, tests, platform_config, ui_adapter
        )
        context = self.build_context(
            cfg,
            target_tests,
            config_path=resolved,
            debug=debug,
            resume=resume,
            stop_file=stop_file,
            execution_mode=execution_mode,
            node_count=node_count,
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
            if not preloaded_config.plugin_assets:
                apply_plugin_assets(preloaded_config, create_registry())
            return preloaded_config, config_path
        cfg, resolved, stale = config_service.load_for_read(config_path)
        if not cfg.plugin_assets:
            apply_plugin_assets(cfg, create_registry())
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

    @staticmethod
    def _apply_platform_defaults(
        cfg: BenchmarkConfig, platform_config: PlatformConfig
    ) -> None:
        """Apply platform defaults without mutating workload selection."""
        if platform_config.output_dir:
            cfg.output_dir = platform_config.output_dir
        if platform_config.report_dir:
            cfg.report_dir = platform_config.report_dir
        if platform_config.data_export_dir:
            cfg.data_export_dir = platform_config.data_export_dir
        if platform_config.loki:
            cfg.loki = platform_config.loki

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
        cfg: BenchmarkConfig,
        tests: Optional[List[str]],
        platform_config: PlatformConfig,
        ui_adapter: UIAdapter | None,
    ) -> List[str]:
        """Determine which workloads to run, skipping those disabled by platform."""
        target_tests = tests or list(cfg.workloads.keys())
        if not target_tests:
            raise ValueError("No workloads selected to run.")

        disabled: list[str] = []
        allowed: list[str] = []
        for name in target_tests:
            workload = cfg.workloads.get(name)
            plugin_name = workload.plugin if workload else name
            if not platform_config.is_plugin_enabled(plugin_name):
                disabled.append(name)
                continue
            allowed.append(name)

        if disabled and ui_adapter:
            ui_adapter.show_warning(
                "Skipping workloads disabled by platform config: "
                + ", ".join(sorted(disabled))
            )
        if not allowed:
            raise ValueError("All selected workloads are disabled by platform config.")
        return allowed

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
        formatter = AnsibleOutputFormatter()
        formatter.emit_task_timings = False
        formatter.emit_task_starts = False
        callback = output_callback
        emit_timing = False
        if callback is None:
            if context.debug:
                # In debug mode, print everything raw for troubleshooting
                def _debug_printer(text: str, end: str = ""):
                    print(text, end=end, flush=True)

                callback = _debug_printer
            else:
                callback = formatter.process

        return self._run_remote(
            context,
            run_id,
            callback,
            formatter,
            ui_adapter,
            stop_token=stop_token,
            emit_timing=emit_timing,
        )

    def _run_remote(
        self,
        context: RunContext,
        run_id: Optional[str],
        output_callback: Callable[[str, str], None],
        formatter: AnsibleOutputFormatter | None,
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None = None,
        emit_timing: bool = True,
    ) -> RunResult:
        """Execute a remote run using the controller with journal integration."""
        coordinator = RemoteRunCoordinator(self)
        return coordinator.run(
            context,
            run_id,
            output_callback,
            formatter,
            ui_adapter,
            stop_token=stop_token,
            emit_timing=emit_timing,
        )

    @staticmethod
    def _attach_controller_jsonl(
        context: RunContext, session: _RemoteSession
    ) -> logging.Handler:
        # We attach to the specific controller logger to ensure we capture INFO logs
        # even if the root logger is at WARNING.
        controller_logger = logging.getLogger("lb_controller")
        controller_logger.setLevel(logging.INFO)
        
        return attach_jsonl_handler(
            controller_logger,
            output_dir=session.journal_path.parent,
            component="controller",
            host=platform.node() or "controller",
            run_id=session.effective_run_id,
            workload="controller",
            package="lb_controller",
            repetition=1,
        )

    @staticmethod
    def _attach_controller_loki(
        context: RunContext, session: _RemoteSession
    ) -> logging.Handler | None:
        loki_cfg = context.config.loki
        handler = attach_loki_handler(
            logging.getLogger(),
            enabled=loki_cfg.enabled,
            endpoint=loki_cfg.endpoint,
            component="controller",
            host=platform.node() or "controller",
            package="lb_controller",
            run_id=session.effective_run_id,
            workload="controller",
            repetition=1,
            labels=loki_cfg.labels,
            batch_size=loki_cfg.batch_size,
            flush_interval_ms=loki_cfg.flush_interval_ms,
            timeout_seconds=loki_cfg.timeout_seconds,
            max_retries=loki_cfg.max_retries,
            max_queue_size=loki_cfg.max_queue_size,
            backoff_base=loki_cfg.backoff_base,
            backoff_factor=loki_cfg.backoff_factor,
        )
        if handler:
            handler.setFormatter(
                JsonlLogFormatter(
                    component="controller",
                    host=platform.node() or "controller",
                    run_id=session.effective_run_id,
                    workload="controller",
                    package="lb_controller",
                    repetition=1,
                )
            )
        return handler

    def _prepare_remote_session(
        self,
        context: RunContext,
        run_id: Optional[str],
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None,
    ) -> _RemoteSession:
        """Initialize journal, dashboard, log files, and session state."""
        return self._session_manager.prepare_remote_session(
            context, run_id, ui_adapter, stop_token
        )

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
        emit_timing: bool,
    ) -> _EventPipeline:
        """Wire output handlers, dedupe, and dashboard logging."""
        dashboard = session.dashboard
        output_cb = pipeline_output_callback(
            dashboard=dashboard, formatter=formatter, output_callback=output_callback
        )
        timing_handler: Callable[[str], None] | None = None
        if emit_timing and formatter and output_callback is not formatter.process:
            def _timing_sink(message: str) -> None:
                output_cb(message, end="\n")

            def _timing_handler(line: str) -> None:
                formatter.process_timing(line, log_sink=_timing_sink)

            timing_handler = _timing_handler
        announce_stop = announce_stop_factory(session, ui_adapter)
        session.stop_token._on_stop = announce_stop  # type: ignore[attr-defined]

        controller_ref: dict[str, BenchmarkController | None] = {"controller": None}
        dedupe = _EventDedupe()
        ingest_event = make_ingest_event(
            session=session,
            dashboard=dashboard,
            controller_ref=controller_ref,
            dedupe=dedupe,
        )
        def event_from_payload(data: dict[str, str]) -> RunEvent | None:
            return event_from_payload_data(data, session, context)
        progress_handler = make_progress_handler(
            session=session,
            context=context,
            ingest_event=ingest_event,
            progress_token=self._progress_token,
        )
        output_with_progress = make_output_tee(
            session=session,
            downstream=output_cb,
            progress_handler=progress_handler,
            timing_handler=timing_handler,
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

    def _run_controller_loop(
        self,
        controller: BenchmarkController,
        context: RunContext,
        session: _RemoteSession,
        pipeline: _EventPipeline,
        ui_adapter: UIAdapter | None,
    ) -> RunExecutionSummary | None:
        """Drive the controller runner with signal handling and logging."""
        return self._execution_loop.run_loop(
            controller, context, session, pipeline, ui_adapter
        )

    def _parse_progress_line(self, line: str) -> dict[str, Any] | None:
        """Parse progress markers emitted by LocalRunner."""
        return parse_progress_line(line, token=self._progress_token)
