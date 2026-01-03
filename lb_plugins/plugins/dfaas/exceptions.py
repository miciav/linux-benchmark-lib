"""Custom exceptions for DFaaS plugin."""

from __future__ import annotations


class DfaasError(Exception):
    """Base exception for DFaaS plugin errors."""


class K6ExecutionError(DfaasError):
    """Raised when k6 test execution fails."""

    def __init__(
        self,
        config_id: str,
        message: str,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> None:
        self.config_id = config_id
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"k6 execution failed for config {config_id}: {message}")


class ConfigExecutionError(DfaasError):
    """Raised when a benchmark configuration fails to execute."""

    def __init__(
        self,
        config_id: str,
        cause: Exception | None = None,
    ) -> None:
        self.config_id = config_id
        self.cause = cause
        message = f"Configuration {config_id} failed"
        if cause:
            message = f"{message}: {cause}"
        super().__init__(message)


class ConfigSkippedError(DfaasError):
    """Raised when a configuration is skipped due to an error (not normal skip)."""

    def __init__(self, config_id: str, reason: str) -> None:
        self.config_id = config_id
        self.reason = reason
        super().__init__(f"Configuration {config_id} skipped: {reason}")


class IndexLoadError(DfaasError):
    """Raised when the existing index cannot be loaded."""

    def __init__(self, path: str, cause: Exception | None = None) -> None:
        self.path = path
        self.cause = cause
        message = f"Failed to load index from {path}"
        if cause:
            message = f"{message}: {cause}"
        super().__init__(message)
