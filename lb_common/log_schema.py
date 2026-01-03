"""Structured JSONL log schema for benchmark components."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


class StructuredLogEvent(BaseModel):
    """Canonical JSONL schema for component logs."""

    timestamp: datetime = Field(...)
    level: str = Field(...)
    component: str = Field(...)
    host: str = Field(...)
    run_id: str = Field(...)
    logger: str = Field(...)
    message: str = Field(...)
    event_type: str = Field(default="log")
    workload: str | None = None
    scenario: str | None = None
    repetition: int | None = None
    tags: Mapping[str, Any] | None = None

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def from_log_record(
        cls,
        record: Any,
        *,
        component: str,
        host: str,
        run_id: str,
        event_type: str = "log",
        workload: str | None = None,
        scenario: str | None = None,
        repetition: int | None = None,
        tags: Mapping[str, Any] | None = None,
    ) -> "StructuredLogEvent":
        """Build a schema instance from a stdlib LogRecord."""
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
        message = record.getMessage()
        return cls(
            timestamp=timestamp,
            level=record.levelname,
            component=component,
            host=host,
            run_id=run_id,
            logger=record.name,
            message=message,
            event_type=event_type,
            workload=workload,
            scenario=scenario,
            repetition=repetition,
            tags=tags,
        )

    def to_json(self) -> str:
        """Serialize to compact JSON for JSONL output."""
        return self.model_dump_json(exclude_none=True)
