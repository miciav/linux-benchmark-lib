"""
Executor for a single test attempt (repetition).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from lb_common.errors import LBError, WorkloadError, error_to_payload
from lb_plugins.api import BaseGenerator, WorkloadPlugin
from lb_runner.engine.stop_context import should_stop
from lb_runner.engine.execution import (
    StopRequested,
    generator_running,
    pre_test_cleanup,
    prepare_generator,
    resolve_duration,
    wait_for_generator,
)
from lb_runner.services.results import build_rep_result
from lb_runner.engine.context import RunnerContext
from lb_runner.engine.metrics import MetricSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepetitionOutcome:
    """Outcome summary for a repetition execution attempt."""

    success: bool
    status: str
    result: Dict[str, Any] | None
    message: str = ""
    error_type: str | None = None
    error_context: dict[str, Any] | None = None


class RepetitionExecutor:
    """Executes a single test attempt (repetition)."""

    def __init__(self, context: RunnerContext):
        self.context = context

    def execute(
        self,
        test_name: str,
        generator: Any,
        repetition: int,
        total_repetitions: int,
        *,
        collectors_enabled: bool = True,
    ) -> Dict[str, Any]:
        """
        Run a single test with the specified generator.

        Args:
            test_name: Name of the test
            generator: Workload generator instance
            repetition: Repetition number
            total_repetitions: Total number of repetitions

        Returns:
            Dictionary containing test results
        """
        logger.info(f"Running test '{test_name}' - Repetition {repetition}")

        workload_dir = self.context.output_manager.workload_output_dir(test_name)
        rep_dir = workload_dir / f"rep{repetition}"
        rep_dir.mkdir(parents=True, exist_ok=True)

        metric_session = self.context.metric_manager.begin_repetition(
            self.context.config,
            test_name=test_name,
            repetition=repetition,
            total_repetitions=total_repetitions,
            current_run_id=self.context.run_id,
            collectors_enabled=collectors_enabled,
        )
        duration = resolve_duration(self.context.config, generator, logger)

        test_start_time: Optional[datetime] = None
        test_end_time: Optional[datetime] = None

        try:
            self._set_log_phase(
                "setup", workload=test_name, repetition=repetition
            )
            pre_test_cleanup(logger)

            if should_stop(self.context.stop_token):
                raise StopRequested("Stopped by user")

            try:
                prepare_generator(generator, self.context.config.warmup_seconds, logger)
            except Exception as exc:
                raise WorkloadError(
                    "Generator setup failed",
                    context={
                        "workload": test_name,
                        "repetition": repetition,
                    },
                    cause=exc,
                ) from exc
            metric_session.start()

            test_start_time = datetime.now()
            try:
                generator.start()
            except Exception as exc:
                raise WorkloadError(
                    "Generator start failed",
                    context={
                        "workload": test_name,
                        "repetition": repetition,
                    },
                    cause=exc,
                ) from exc
            
            # Phase: Running (None)
            self._set_log_phase(
                None, workload=test_name, repetition=repetition
            )
            logger.info("Running test for %s seconds", duration)

            try:
                test_end_time = wait_for_generator(
                    generator,
                    duration,
                    test_name,
                    repetition,
                    logger=logger,
                )
            except StopRequested:
                raise
            except Exception as exc:
                raise WorkloadError(
                    "Generator execution failed",
                    context={
                        "workload": test_name,
                        "repetition": repetition,
                    },
                    cause=exc,
                ) from exc

            self._set_log_phase(
                "teardown", workload=test_name, repetition=repetition
            )
            self._cleanup_after_run(generator, metric_session)
            
            # Phase: Done (None)
            self._set_log_phase(
                None, workload=test_name, repetition=repetition
            )

        except Exception:
            # Ensure cleanup happens even on error
            self._cleanup_after_run(generator, metric_session)
            raise

        finally:
            metric_session.close()

        result = self._finalize_single_test(
            generator,
            metric_session,
            workload_dir,
            rep_dir,
            test_name,
            repetition,
            test_start_time,
            test_end_time,
        )

        return result

    def run_attempt(
        self,
        test_name: str,
        generator: Any,
        repetition: int,
        total_repetitions: int,
        *,
        plugin: WorkloadPlugin | None = None,
        collectors_enabled: bool = True,
    ) -> RepetitionOutcome:
        """Execute a repetition and return a normalized outcome summary."""
        try:
            result = self.execute(
                test_name=test_name,
                generator=generator,
                repetition=repetition,
                total_repetitions=total_repetitions,
                collectors_enabled=collectors_enabled,
            )
            self._cleanup_generator(generator, test_name, repetition)
            self._process_results(test_name, [result], plugin=plugin)
            success = bool(result.get("success", True))
            message = "" if success else str(result.get("error") or "")
            return RepetitionOutcome(
                success=success,
                status="done" if success else "failed",
                result=result,
                message=message,
                error_type=result.get("error_type") if not success else None,
                error_context=result.get("error_context") if not success else None,
            )
        except StopRequested:
            return RepetitionOutcome(
                success=False,
                status="stopped",
                result=None,
            )
        except LBError as exc:
            logger.exception(
                "Workload '%s' failed on repetition %s", test_name, repetition
            )
            outcome = self._handle_failure(
                test_name=test_name,
                repetition=repetition,
                generator=generator,
                error=exc,
                plugin=plugin,
            )
            return outcome
        except Exception:
            logger.exception(
                "Unexpected failure running workload '%s' rep %s",
                test_name,
                repetition,
            )
            raise

    def handle_failure(
        self,
        *,
        test_name: str,
        repetition: int,
        generator: Any,
        error: LBError,
        plugin: WorkloadPlugin | None,
    ) -> RepetitionOutcome:
        """Persist failure details and return a failure outcome."""
        return self._handle_failure(
            test_name=test_name,
            repetition=repetition,
            generator=generator,
            error=error,
            plugin=plugin,
        )

    def _cleanup_after_run(
        self,
        generator: Any,
        metric_session: MetricSession,
        generator_started: bool = True,
    ) -> None:
        if generator_started and hasattr(generator, "stop"):
            try:
                if generator_running(generator):
                    logger.info("Stopping generator due to error or interruption...")
                generator.stop()
            except Exception as exc:
                logger.error("Failed to stop generator during cleanup: %s", exc)
        metric_session.stop()

    def _finalize_single_test(
        self,
        generator: Any,
        metric_session: MetricSession,
        workload_dir: Path,
        rep_dir: Path,
        test_name: str,
        repetition: int,
        test_start_time: datetime | None,
        test_end_time: datetime | None,
    ) -> Dict[str, Any]:
        result = build_rep_result(
            test_name=test_name,
            repetition=repetition,
            rep_dir=rep_dir,
            generator_result=generator.get_result(),
            test_start_time=test_start_time,
            test_end_time=test_end_time,
        )
        duration_seconds = result.get("duration_seconds", 0) or 0
        if duration_seconds:
            logger.info("Repetition %s completed in %.2fs", repetition, duration_seconds)

        metric_session.collect(workload_dir, rep_dir, test_name, repetition, result)
        self.context.output_manager.persist_rep_result(rep_dir, result)
        return result

    def _set_log_phase(
        self,
        phase: str | None,
        *,
        workload: str,
        repetition: int,
    ) -> None:
        if not self.context.run_id:
            return
        output_dir = self.context.output_manager.output_root() or self.context.config.output_dir
        self.context.log_manager.attach(
            output_dir=output_dir,
            run_id=self.context.run_id,
            workload=workload,
            repetition=repetition,
            phase=phase,
        )

    def _cleanup_generator(
        self,
        generator: Any,
        test_name: str,
        repetition: int,
    ) -> None:
        if not isinstance(generator, BaseGenerator):
            return
        try:
            generator.cleanup()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.warning(
                "Generator cleanup failed for %s rep %s: %s",
                test_name,
                repetition,
                exc,
            )

    def _process_results(
        self,
        test_name: str,
        results: list[dict[str, Any]],
        *,
        plugin: WorkloadPlugin | None = None,
    ) -> None:
        target_root = self.context.output_manager.workload_output_dir(test_name)
        self.context.output_manager.process_results(
            plugin=plugin,
            results=results,
            target_root=target_root,
            test_name=test_name,
        )

    def _handle_failure(
        self,
        *,
        test_name: str,
        repetition: int,
        generator: Any,
        error: LBError,
        plugin: WorkloadPlugin | None,
    ) -> RepetitionOutcome:
        error_payload = error_to_payload(error)
        workload_dir = self.context.output_manager.workload_output_dir(test_name)
        rep_dir = workload_dir / f"rep{repetition}"
        rep_dir.mkdir(parents=True, exist_ok=True)
        generator_result: Any = {}
        if generator is not None and hasattr(generator, "get_result"):
            try:
                generator_result = generator.get_result()
            except Exception:
                logger.debug(
                    "Failed to read generator result after error", exc_info=True
                )
        result = build_rep_result(
            test_name=test_name,
            repetition=repetition,
            rep_dir=rep_dir,
            generator_result=generator_result,
            test_start_time=None,
            test_end_time=None,
        )
        result.update(error_payload)
        result["success"] = False
        self._cleanup_generator(generator, test_name, repetition)
        try:
            self.context.output_manager.persist_rep_result(rep_dir, result)
            self._process_results(test_name, [result], plugin=plugin)
        except Exception:
            logger.exception(
                "Failed to persist failure result for %s rep %s",
                test_name,
                repetition,
            )
        return RepetitionOutcome(
            success=False,
            status="failed",
            result=result,
            message=error_payload.get("error", ""),
            error_type=error_payload.get("error_type"),
            error_context=error_payload.get("error_context"),
        )
