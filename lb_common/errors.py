"""Shared error taxonomy for linux-benchmark-lib."""

from __future__ import annotations

from typing import Any, Mapping, TypeVar


def _normalize_context_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return normalize_context(value)
    if isinstance(value, list):
        return [_normalize_context_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_context_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def normalize_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-friendly copy of an error context mapping."""
    return {key: _normalize_context_value(val) for key, val in context.items()}


class LBError(Exception):
    """Base error type for typed failure handling."""

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.context = normalize_context(context or {})
        if cause is not None:
            self.__cause__ = cause

    @property
    def error_type(self) -> str:
        return self.__class__.__name__

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.error_type, "message": str(self), "context": self.context}


class WorkloadError(LBError):
    """Failure while preparing or executing a workload generator."""


class MetricCollectionError(LBError):
    """Failure during metric collection or persistence."""


class ResultPersistenceError(LBError):
    """Failure persisting results or artifacts."""


class OutputParseError(LBError):
    """Failure parsing structured output streams."""


class RemoteExecutionError(LBError):
    """Failure in remote execution or orchestration layers."""


class ConfigurationError(LBError):
    """Failure due to invalid configuration."""


T = TypeVar("T", bound=LBError)


def wrap_error(
    error_cls: type[T],
    message: str,
    *,
    context: Mapping[str, Any] | None = None,
    cause: Exception | None = None,
) -> T:
    """Create a typed LBError with optional context and cause."""
    return error_cls(message, context=context, cause=cause)


def error_to_payload(error: LBError) -> dict[str, Any]:
    """Convert an LBError to a result/journal payload."""
    return {
        "error_type": error.error_type,
        "error": str(error),
        "error_context": error.context,
    }
