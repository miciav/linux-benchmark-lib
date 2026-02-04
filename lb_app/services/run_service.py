"""Application-facing run orchestration helpers for the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from lb_controller.api import (
    BenchmarkConfig,
    BenchmarkController,
    PlatformConfig,
    StopToken,
)
from lb_plugins.api import PluginRegistry

from lb_app.ui_interfaces import UIAdapter
from lb_app.services.run_pipeline import parse_progress_line
from lb_app.services.run_output import AnsibleOutputFormatter
from lb_app.services.run_plan import build_run_plan
from lb_app.services.run_types import RunContext, RunResult
from lb_app.services.run_context_builder import (
    RunContextBuilder,
    apply_overrides,
    resolve_target_tests,
)
from lb_app.services.run_execution import (
    ControllerLogAttachmentService,
    RunExecutionCoordinator,
)
from lb_app.services.execution_loop import RunExecutionLoop
from lb_app.services.session_manager import SessionManager

if TYPE_CHECKING:
    from logging import Handler
    from lb_controller.api import RunExecutionSummary
    from lb_app.services.run_types import _EventPipeline, _RemoteSession


class RunService:
    """Coordinate benchmark execution for CLI commands."""

    def __init__(self, registry_factory: Callable[[], PluginRegistry]):
        self._registry_factory = registry_factory
        self._progress_token = "LB_EVENT"
        self._execution_loop = RunExecutionLoop()
        self._session_manager = SessionManager(registry_factory)
        self._context_builder = RunContextBuilder(registry_factory)
        self._log_attachment_service = ControllerLogAttachmentService()
        self._execution_coordinator = RunExecutionCoordinator(
            session_manager=self._session_manager,
            execution_loop=self._execution_loop,
            progress_token=self._progress_token,
            log_attachment_service=self._log_attachment_service,
        )

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
        apply_overrides(cfg, intensity=intensity, debug=debug)

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
        return self._context_builder.build_context(
            cfg,
            tests,
            config_path=config_path,
            debug=debug,
            resume=resume,
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
        return self._context_builder.create_session(
            config_service,
            tests=tests,
            config_path=config_path,
            run_id=run_id,
            resume=resume,
            repetitions=repetitions,
            debug=debug,
            intensity=intensity,
            ui_adapter=ui_adapter,
            setup=setup,
            stop_file=stop_file,
            execution_mode=execution_mode,
            node_count=node_count,
            preloaded_config=preloaded_config,
        )

    @staticmethod
    def _resolve_target_tests(
        cfg: BenchmarkConfig,
        tests: Optional[List[str]],
        platform_config: PlatformConfig,
        ui_adapter: UIAdapter | None,
    ) -> List[str]:
        """Determine which workloads to run, skipping those disabled by platform."""
        return resolve_target_tests(cfg, tests, platform_config, ui_adapter)

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
        return self._execution_coordinator.run_remote(
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
    ) -> Handler:
        return self._execution_coordinator._attach_controller_jsonl(context, session)

    @staticmethod
    def _attach_controller_loki(
        context: RunContext, session: _RemoteSession
    ) -> Handler | None:
        return self._execution_coordinator._attach_controller_loki(context, session)

    def _prepare_remote_session(
        self,
        context: RunContext,
        run_id: Optional[str],
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None,
    ) -> _RemoteSession:
        """Initialize journal, dashboard, log files, and session state."""
        return self._execution_coordinator._prepare_remote_session(
            context, run_id, ui_adapter, stop_token
        )

    def _short_circuit_empty_run(
        self, context: RunContext, session: _RemoteSession, ui_adapter: UIAdapter | None
    ) -> RunResult:
        """Handle resume cases where nothing remains to run."""
        return self._execution_coordinator._short_circuit_empty_run(
            context, session, ui_adapter
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
        return self._execution_coordinator._build_event_pipeline(
            context,
            session,
            formatter,
            output_callback,
            ui_adapter,
            emit_timing,
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
        return self._execution_coordinator._run_controller_loop(
            controller, context, session, pipeline, ui_adapter
        )

    def _parse_progress_line(self, line: str) -> dict[str, Any] | None:
        """Parse progress markers emitted by LocalRunner."""
        return parse_progress_line(line, token=self._progress_token)
