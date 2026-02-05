"""Helpers for workload execution flow."""

from __future__ import annotations

import logging
import platform
import subprocess
import time
from datetime import datetime
from typing import Any

from lb_runner.engine.stop_token import StopToken
from lb_runner.engine.stop_context import should_stop


logger = logging.getLogger(__name__)


def pre_test_cleanup(logger: logging.Logger) -> None:
    """Perform pre-test cleanup operations."""
    logger.info("Performing pre-test cleanup")

    if platform.system() == "Linux":
        try:
            subprocess.run(["sync"], check=True)
            try:
                subprocess.run(
                    ["sudo", "-n", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
                    check=True,
                    capture_output=True,
                )
                logger.info("Cleared filesystem caches")
            except Exception:
                logger.debug("Skipping cache clearing (no sudo access)")
        except Exception as exc:
            logger.warning("Failed to perform pre-test cleanup: %s", exc)


def resolve_duration(config: Any, generator: Any, logger: logging.Logger) -> int:
    """Resolve runtime duration based on config defaults and generator hints."""
    duration = int(getattr(config, "test_duration_seconds", 0))
    if hasattr(generator, "expected_runtime_seconds"):
        try:
            expected = int(getattr(generator, "expected_runtime_seconds"))
            if expected > duration:
                logger.info(
                    "Extending test duration to %s seconds based on workload hint",
                    expected,
                )
                duration = expected
        except Exception:
            logger.debug(
                "Failed to read expected runtime from generator; using default duration"
            )
    return duration


def prepare_generator(
    generator: Any, warmup_seconds: int, logger: logging.Logger
) -> None:
    """Prepare the generator and optionally sleep for warmup."""
    try:
        generator.prepare()
    except Exception as exc:
        logger.error("Generator setup failed: %s", exc)
        raise
    if warmup_seconds > 0:
        logger.info("Warmup period: %s seconds", warmup_seconds)
        time.sleep(warmup_seconds)


def start_collectors(collectors: list[Any], logger: logging.Logger) -> None:
    """Start all collectors, logging errors but continuing."""
    for collector in collectors:
        try:
            collector.start()
        except Exception as exc:
            logger.error("Failed to start collector %s: %s", collector.name, exc)


def wait_for_generator(
    generator: Any,
    duration: int,
    test_name: str,
    repetition: int,
    logger: logging.Logger,
    stop_token: StopToken | None = None,
) -> datetime:
    """Block until the generator stops or exceeds the maximum duration."""
    safety_buffer = 10
    max_wait = duration + safety_buffer
    elapsed = 0
    last_progress_log = 0
    while elapsed < max_wait:
        if should_stop(stop_token):
            raise StopRequested("Stopped by user")
        if not generator_running(generator):
            break
        time.sleep(1)
        elapsed += 1
        if should_log_progress(duration, elapsed, last_progress_log):
            percent = int((min(elapsed, duration) / duration) * 100)
            logger.info("Progress for %s rep %s: %s%%", test_name, repetition, percent)
            last_progress_log = elapsed
    if generator_running(generator):
        logger.warning(
            "Workload exceeded %ss (duration + safety). Forcing stop.", max_wait
        )
        generator.stop()
    return datetime.now()


def cleanup_after_run(
    generator: Any,
    collectors: list[Any],
    logger: logging.Logger,
    generator_started: bool = True,
) -> None:
    """Best-effort cleanup for generator and collectors."""
    if generator_started and hasattr(generator, "stop"):
        try:
            if generator_running(generator):
                logger.info("Stopping generator due to error or interruption...")
            generator.stop()
        except Exception as exc:
            logger.error("Failed to stop generator during cleanup: %s", exc)

    for collector in collectors:
        try:
            collector.stop()
        except Exception as exc:
            logger.error("Failed to stop collector %s: %s", collector.name, exc)


def should_log_progress(duration: int, elapsed: int, last_progress_log: int) -> bool:
    """Determine whether a progress log should be emitted."""
    if not duration:
        return False
    step = max(1, duration // 10)
    return elapsed % step == 0 and elapsed != last_progress_log


def generator_running(generator: Any) -> bool:
    """
    Safely interpret the generator's running flag.

    MagicMock instances used in tests may return a non-bool sentinel for
    `_is_running`; treat any non-bool as False to avoid long sleep loops.
    """
    state = getattr(generator, "_is_running", False)
    return state is True or (isinstance(state, bool) and state)


class StopRequested(Exception):
    """Raised when execution is stopped by user request."""
