"""Public API surface for lb_common."""

from lb_common.config.env import (
    parse_bool_env,
    parse_float_env,
    parse_int_env,
    parse_labels_env,
)
from lb_common.discovery.entrypoints import (
    discover_entrypoints,
    load_entrypoint,
    load_pending_entrypoints,
)
from lb_common.errors import (
    ConfigurationError,
    LBError,
    MetricCollectionError,
    OutputParseError,
    RemoteExecutionError,
    ResultPersistenceError,
    WorkloadError,
    error_to_payload,
    normalize_context,
    wrap_error,
)
from lb_common.logs.core import (
    attach_jsonl_handler,
    attach_loki_handler,
    configure_logging,
)
from lb_common.logs.handlers.jsonl_handler import JsonlLogFormatter
from lb_common.logs.handlers.loki_handler import normalize_loki_endpoint
from lb_common.models.hosts import RemoteHostSpec
from lb_common.models.run_info import RunInfo
from lb_common.observability.grafana_client import GrafanaClient

__all__ = [
    "ConfigurationError",
    "GrafanaClient",
    "JsonlLogFormatter",
    "LBError",
    "MetricCollectionError",
    "OutputParseError",
    "RemoteExecutionError",
    "RemoteHostSpec",
    "ResultPersistenceError",
    "RunInfo",
    "WorkloadError",
    "attach_jsonl_handler",
    "attach_loki_handler",
    "configure_logging",
    "discover_entrypoints",
    "error_to_payload",
    "load_entrypoint",
    "load_pending_entrypoints",
    "normalize_context",
    "normalize_loki_endpoint",
    "parse_bool_env",
    "parse_float_env",
    "parse_int_env",
    "parse_labels_env",
    "wrap_error",
]
