"""
Executor for a single test attempt (repetition).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from lb_common.errors import WorkloadError
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

logger = logging.getLogger(__name__)


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

        collectors = self.context.metric_manager.create_collectors(self.context.config)
        duration = resolve_duration(self.context.config, generator, logger)

        # Attach event logger (MetricManager)
        log_handler = self.context.metric_manager.attach_event_logger(
            test_name, repetition, total_repetitions, self.context.run_id
        )

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
            self.context.metric_manager.start_collectors(collectors)

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
            self._cleanup_after_run(generator, collectors)
            
            # Phase: Done (None)
            self._set_log_phase(
                None, workload=test_name, repetition=repetition
            )

        except Exception:
            # Ensure cleanup happens even on error
            self._cleanup_after_run(generator, collectors)
            raise

        finally:
            if log_handler:
                self.context.metric_manager.detach_event_logger(log_handler)

        result = self._finalize_single_test(
            generator,
            collectors,
            workload_dir,
            rep_dir,
            test_name,
            repetition,
            test_start_time,
            test_end_time,
        )

        return result

    def _cleanup_after_run(
        self, generator: Any, collectors: list[Any], generator_started: bool = True
    ) -> None:
        if generator_started and hasattr(generator, "stop"):
            try:
                if generator_running(generator):
                    logger.info("Stopping generator due to error or interruption...")
                generator.stop()
            except Exception as exc:
                logger.error("Failed to stop generator during cleanup: %s", exc)
        self.context.metric_manager.stop_collectors(collectors)

    def _finalize_single_test(
        self,
        generator: Any,
        collectors: list[Any],
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

        self.context.metric_manager.collect_metrics(
            collectors, workload_dir, rep_dir, test_name, repetition, result
        )
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
