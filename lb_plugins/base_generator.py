"""
Base generator abstract class for workload generators.

This module defines the common interface that all workload generators must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
import subprocess
import threading
from typing import Any, Optional, Protocol

from lb_common.api import WorkloadError, error_to_payload


logger = logging.getLogger(__name__)


class BaseGenerator(ABC):
    """Abstract base class for all workload generators."""

    def __init__(self, name: str):
        """
        Initialize the base generator.

        Args:
            name: Name of the generator
        """
        self.name = name
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._result: Optional[Any] = None
        self._error: WorkloadError | None = None

    @abstractmethod
    def _run_command(self) -> None:
        """
        Run the actual command or process to generate workload.

        This method should handle the process of workload generation.
        """
        pass

    @abstractmethod
    def _validate_environment(self) -> bool:
        """
        Validate that the generator can run in the current environment.

        Returns:
            True if the environment is valid, False otherwise
        """
        pass

    def prepare(self) -> None:
        """
        Optional pre-run hook executed synchronously before collectors start.

        Generators can override to perform expensive setup (e.g., build binaries)
        so collectors do not capture that time. Default is a no-op.
        """
        return None

    def cleanup(self) -> None:
        """
        Optional post-run hook executed after collectors stop and results are persisted.

        Generators can override to remove temporary artifacts created during a single
        repetition without affecting shared setup/provisioning.
        """
        return None

    @abstractmethod
    def _stop_workload(self) -> None:
        """
        Stop the actual workload process.

        This method must be implemented by subclasses to ensure the
        underlying process (e.g., subprocess) is terminated correctly.
        """
        pass

    def start(self) -> None:
        """Start the workload generation in a background thread."""
        if self._is_running:
            logger.warning("%s generator is already running", self.name)
            return

        self._ensure_environment()
        self._is_running = True
        self._thread = threading.Thread(target=self._run_worker)
        self._thread.start()

        logger.info("%s generator started", self.name)

    def stop(self) -> None:
        """Stop the workload generation."""
        if self._is_running:
            self._stop_if_running()
        else:
            logger.debug("%s generator was already stopped or finished", self.name)

        # Always ensure the thread is joined to avoid zombies
        self._join_thread()
        logger.info("%s generator stopped", self.name)

    def _stop_if_running(self) -> None:
        # Signal the workload to stop only if it thinks it's running
        self._stop_workload()
        self._is_running = False

    def _join_thread(self) -> None:
        # Always ensure the thread is joined to avoid zombies
        if not self._thread or not self._thread.is_alive():
            return
        try:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning(f"{self.name} thread did not terminate gracefully")
        except Exception as exc:
            logger.error(f"Error joining thread for {self.name}: {exc}")

    def check_prerequisites(self) -> bool:
        """
        Check if the generator's prerequisites are met.

        Delegates to the protected _validate_environment method.
        """
        return self._validate_environment()

    def get_result(self) -> Any:
        """
        Get the result of the workload generation.

        Returns:
            The result obtained from the workload generation
        """
        return self._result

    def get_error(self) -> WorkloadError | None:
        """Return any captured workload error."""
        return self._error

    def _set_error(self, error: WorkloadError) -> None:
        self._error = error
        payload = error_to_payload(error)
        if isinstance(self._result, dict):
            self._result.update(payload)
        else:
            self._result = payload

    def _ensure_environment(self) -> None:
        if self._validate_environment():
            return
        raise WorkloadError(
            f"{self.name} generator cannot run in this environment",
            context={"workload": self.name},
        )

    def _run_worker(self) -> None:
        try:
            self._run_command()
        except WorkloadError as exc:
            self._set_error(exc)
            logger.error("%s workload error: %s", self.name, exc)
        except Exception as exc:
            error = WorkloadError(
                f"{self.name} workload failed",
                context={"workload": self.name},
                cause=exc,
            )
            self._set_error(error)
            logger.exception("%s workload crashed", self.name)
        finally:
            # Always clear running flag when the worker exits (success or failure)
            self._is_running = False


@dataclass
class CommandSpec:
    """Command execution specification."""

    cmd: list[str]
    popen_kwargs: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: Optional[int] = None


class CommandSpecBuilder(Protocol):
    """Strategy interface for building command specs."""

    def build(self, config: Any) -> CommandSpec: ...


class ResultParser(Protocol):
    """Strategy interface for parsing command results."""

    def parse(self, result: dict[str, Any]) -> dict[str, Any]: ...


class CommandGenerator(BaseGenerator):
    """Base class for command-driven workload generators."""

    def __init__(
        self,
        name: str,
        config: Any,
        *,
        command_builder: CommandSpecBuilder | None = None,
        result_parser: ResultParser | None = None,
    ):
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen[str]] = None
        self._command_builder = command_builder
        self._result_parser = result_parser
        self._active_timeout: Optional[int] = None

    @abstractmethod
    def _build_command(self) -> list[str]:
        """Return the command to execute."""
        raise NotImplementedError

    def _popen_kwargs(self) -> dict[str, Any]:
        return {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}

    def _timeout_seconds(self) -> Optional[int]:
        if self._active_timeout is not None:
            return self._active_timeout
        timeout = getattr(self.config, "timeout", None)
        if timeout is None:
            return None
        return timeout + int(getattr(self.config, "timeout_buffer", 0))

    def _log_command(self, cmd: list[str]) -> None:
        logger.info("Running command: %s", " ".join(cmd))

    def _consume_process_output(self, proc: subprocess.Popen[str]) -> tuple[str, str]:
        stdout, stderr = proc.communicate(timeout=self._timeout_seconds())
        return stdout or "", stderr or ""

    def _build_result(
        self,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "command": " ".join(cmd),
        }
        if hasattr(self.config, "max_retries"):
            result["max_retries"] = self.config.max_retries
        if hasattr(self.config, "tags"):
            result["tags"] = self.config.tags
        return result

    def _log_failure(
        self, returncode: int, stdout: str, stderr: str, cmd: list[str]
    ) -> None:
        logger.error("%s failed with return code %s", self.name, returncode)

    def _after_run(
        self,
        cmd: list[str],
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> None:
        return None

    def _build_command_spec(self) -> CommandSpec:
        if self._command_builder is not None:
            spec = self._command_builder.build(self.config)
        else:
            spec = CommandSpec(cmd=self._build_command())

        base_kwargs = self._popen_kwargs()
        if spec.popen_kwargs:
            base_kwargs.update(spec.popen_kwargs)
        spec.popen_kwargs = base_kwargs

        if spec.timeout_seconds is None:
            spec.timeout_seconds = self._timeout_seconds()
        return spec

    def _run_command(self) -> None:
        spec = self._build_command_spec()
        cmd = spec.cmd
        self._log_command(cmd)

        try:
            self._active_timeout = spec.timeout_seconds
            self._process = subprocess.Popen(cmd, **spec.popen_kwargs)
            stdout, stderr = self._consume_process_output(self._process)
            returncode = self._process.returncode
            self._result = self._build_result(cmd, stdout, stderr, returncode)
            if returncode not in (None, 0):
                self._log_failure(returncode, stdout, stderr, cmd)
                error = WorkloadError(
                    f"{self.name} returned non-zero exit code",
                    context={
                        "workload": self.name,
                        "returncode": returncode,
                        "command": " ".join(cmd),
                    },
                )
                self._set_error(error)
            self._after_run(cmd, stdout, stderr, returncode)
            if self._result_parser and isinstance(self._result, dict):
                try:
                    self._result = self._result_parser.parse(self._result)
                except Exception as exc:
                    error = WorkloadError(
                        f"{self.name} result parsing failed",
                        context={"workload": self.name},
                        cause=exc,
                    )
                    self._set_error(error)
        except subprocess.TimeoutExpired:
            timeout = self._timeout_seconds()
            logger.error(
                "%s timed out after %s seconds. Terminating process.",
                self.name,
                timeout,
            )
            error = WorkloadError(
                f"{self.name} timed out after {timeout}s",
                context={"workload": self.name, "timeout_seconds": timeout},
            )
            self._result = {"returncode": -1}
            self._set_error(error)
            self._stop_workload()
        except Exception as exc:
            logger.error("Error running %s: %s", self.name, exc)
            error = WorkloadError(
                f"{self.name} execution failed",
                context={"workload": self.name},
                cause=exc,
            )
            self._result = {"returncode": -2}
            self._set_error(error)
        finally:
            self._process = None
            self._active_timeout = None

    def _stop_workload(self) -> None:
        proc = self._process
        if proc and proc.poll() is None:
            logger.info("Terminating %s process", self.name)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing %s process", self.name)
                proc.kill()
                proc.wait()
