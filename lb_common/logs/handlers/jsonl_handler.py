"""JSONL log handler for structured component logs."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping

from lb_common.logs.schema import StructuredLogEvent


DEFAULT_JSONL_TEMPLATE = "{output_dir}/logs/{component}-{host}.jsonl"


class JsonlLogFormatter(logging.Formatter):
    """Format LogRecords as structured JSONL."""

    def __init__(
        self,
        *,
        component: str,
        host: str,
        run_id: str,
        event_type: str = "log",
        workload: str | None = None,
        package: str | None = None,
        plugin: str | None = None,
        scenario: str | None = None,
        repetition: int | None = None,
        tags: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._component = component
        self._host = host
        self._run_id = run_id
        self._event_type = event_type
        self._workload = workload
        self._package = package
        self._plugin = plugin
        self._scenario = scenario
        self._repetition = repetition
        self._tags = tags

    def format(self, record: logging.LogRecord) -> str:
        event_type = _resolve_record_value(record, "lb_event_type", self._event_type)
        workload = _resolve_record_value(record, "lb_workload", self._workload)
        package = _resolve_record_value(record, "lb_package", self._package)
        plugin = _resolve_record_value(record, "lb_plugin", self._plugin)
        scenario = _resolve_record_value(record, "lb_scenario", self._scenario)
        repetition = _resolve_record_value(record, "lb_repetition", self._repetition)
        tags = _merge_record_tags(self._tags, record)
        event = StructuredLogEvent.from_log_record(
            record,
            component=self._component,
            host=self._host,
            run_id=self._run_id,
            event_type=event_type,
            workload=workload,
            package=package,
            plugin=plugin,
            scenario=scenario,
            repetition=repetition,
            tags=tags,
        )
        return event.to_json()


def _resolve_record_value(
    record: logging.LogRecord, attribute: str, fallback: Any
) -> Any:
    value = getattr(record, attribute, None)
    return value if value is not None else fallback


def _merge_record_tags(
    base_tags: Mapping[str, Any] | None, record: logging.LogRecord
) -> dict[str, Any] | None:
    tags = dict(base_tags or {})
    phase = getattr(record, "lb_phase", None)
    if phase:
        tags["phase"] = phase
    record_tags = getattr(record, "lb_tags", None)
    if isinstance(record_tags, Mapping):
        tags.update(record_tags)
    return tags or None


def resolve_jsonl_path(
    template: str,
    *,
    output_dir: Path | str,
    component: str,
    host: str,
    run_id: str,
) -> Path:
    """Resolve a JSONL log path from the provided template."""
    resolved = template.format(
        output_dir=output_dir,
        component=component,
        host=host,
        run_id=run_id,
    )
    return Path(resolved).expanduser().resolve()


class JsonlLogHandler(RotatingFileHandler):
    """Rotating file handler that writes structured JSONL records."""

    def __init__(
        self,
        *,
        output_dir: Path | str,
        component: str,
        host: str,
        run_id: str,
        path_template: str = DEFAULT_JSONL_TEMPLATE,
        event_type: str = "log",
        workload: str | None = None,
        package: str | None = None,
        plugin: str | None = None,
        scenario: str | None = None,
        repetition: int | None = None,
        tags: Mapping[str, Any] | None = None,
        max_bytes: int = 0,
        backup_count: int = 0,
    ) -> None:
        log_path = resolve_jsonl_path(
            path_template,
            output_dir=output_dir,
            component=component,
            host=host,
            run_id=run_id,
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        self.setFormatter(
            JsonlLogFormatter(
                component=component,
                host=host,
                run_id=run_id,
                event_type=event_type,
                workload=workload,
                package=package,
                plugin=plugin,
                scenario=scenario,
                repetition=repetition,
                tags=tags,
            )
        )
