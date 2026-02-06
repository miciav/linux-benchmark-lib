"""PEVA-faas configuration models."""

from __future__ import annotations

import os
import re
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator

from lb_common.api import parse_bool_env, parse_int_env

from ...interface import BasePluginConfig
from .strategies import (
    CustomRateStrategy,
    ExponentialRateStrategy,
    LinearRateStrategy,
    RandomRateStrategy,
)

# Discriminated union for rate strategies
RateStrategyUnion = Annotated[
    Union[
        LinearRateStrategy,
        RandomRateStrategy,
        ExponentialRateStrategy,
        CustomRateStrategy,
    ],
    Discriminator("type"),
]

_ALLOWED_HTTP_METHODS = {
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "PATCH",
    "HEAD",
    "OPTIONS",
}
_DURATION_RE = re.compile(r"^(?P<value>[0-9]+)(?P<unit>ms|s|m|h)$")
_DEFAULT_K6_WORKSPACE_ROOT = "/home/ubuntu/.peva_faas-k6"
_DEFAULT_QUERIES_PATH = str(Path(__file__).parent / "queries.yml")


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two dictionaries."""
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_validator_values(values: Any, model_cls: type[BaseModel]) -> Any:
    if isinstance(values, model_cls):
        return values
    if values is None:
        return {}
    if not isinstance(values, dict):
        return values
    return values


def _set_env_bool(values: dict[str, Any], key: str, env_var: str) -> None:
    if values.get(key) is None:
        env_value = parse_bool_env(os.environ.get(env_var))
        if env_value is not None:
            values[key] = env_value


def _set_env_str(values: dict[str, Any], key: str, env_var: str) -> None:
    if not values.get(key):
        env_value = os.environ.get(env_var)
        if env_value:
            values[key] = env_value


def _set_env_int(values: dict[str, Any], key: str, env_var: str) -> None:
    if values.get(key) is None:
        env_value = parse_int_env(os.environ.get(env_var))
        if env_value is not None:
            values[key] = env_value


def _load_config_data(config_path: Path) -> dict[str, Any]:
    """Load and merge config from YAML file."""
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    data = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a mapping at the top level.")
    common = data.get("common", {}) or {}
    plugin_section = data.get("plugins", {}) or {}
    plugin_data = plugin_section.get("peva_faas", {})
    if not isinstance(common, dict) or not isinstance(plugin_data, dict):
        raise ValueError(
            "Config sections 'common' and 'plugins.peva_faas' must be mappings."
        )
    return _deep_merge(common, plugin_data)


def _looks_like_default_queries_path(path: Path) -> bool:
    """Return True if the path matches the default repo layout."""
    normalized = tuple(part.lower() for part in path.parts)
    tail_peva = ("lb_plugins", "plugins", "peva_faas", "queries.yml")
    return len(normalized) >= len(tail_peva) and normalized[-len(tail_peva) :] == tail_peva


class DfaasFunctionConfig(BaseModel):
    """Function metadata and payload configuration."""

    name: str = Field(min_length=1, description="OpenFaaS function name")
    method: str = Field(default="GET", description="HTTP method used by k6")
    body: str = Field(default="", description="Request payload body")
    headers: dict[str, str] = Field(
        default_factory=dict, description="HTTP headers for the request"
    )
    max_rate: int | None = Field(
        default=None,
        ge=0,
        description="Optional per-function maximum rate (requests per second)",
    )

    model_config = {"extra": "ignore"}

    @field_validator("method")
    @classmethod
    def _validate_method(cls, value: str) -> str:
        method = value.upper().strip()
        if method not in _ALLOWED_HTTP_METHODS:
            raise ValueError(f"Unsupported HTTP method: {value}")
        return method


class DfaasRatesConfig(BaseModel):
    """Rate list configuration (inclusive range).

    .. deprecated::
        Use ``rate_strategy`` with ``LinearRateStrategy`` instead.
        This class is kept for backward compatibility only.
    """

    min_rate: int = Field(default=0, ge=0, description="Minimum requests per second")
    max_rate: int = Field(default=200, ge=0, description="Maximum requests per second")
    step: int = Field(default=10, gt=0, description="Step between rates")

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _validate_bounds(self) -> "DfaasRatesConfig":
        if self.max_rate < self.min_rate:
            raise ValueError("rates.max_rate must be >= rates.min_rate")
        return self


class DfaasCombinationConfig(BaseModel):
    """Function combination configuration."""

    min_functions: int = Field(default=1, ge=1, description="Minimum functions per run")
    max_functions: int = Field(
        default=2, ge=1, description="Maximum functions (exclusive)"
    )

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _validate_bounds(self) -> "DfaasCombinationConfig":
        if self.max_functions <= self.min_functions:
            raise ValueError(
                "combinations.max_functions must be > combinations.min_functions"
            )
        return self


class DfaasCooldownConfig(BaseModel):
    """Cooldown settings between iterations."""

    max_wait_seconds: int = Field(default=180, ge=0, description="Cooldown timeout")
    sleep_step_seconds: int = Field(default=5, gt=0, description="Cooldown sleep step")
    idle_threshold_pct: float = Field(
        default=15, ge=0, le=100, description="Idle threshold percentage"
    )

    model_config = {"extra": "ignore"}


class DfaasOverloadConfig(BaseModel):
    """Overload thresholds (legacy behavior)."""

    cpu_overload_pct_of_capacity: float = Field(
        default=80, ge=0, le=100, description="CPU overload threshold (percent)"
    )
    ram_overload_pct: float = Field(
        default=90, ge=0, le=100, description="RAM overload threshold (percent)"
    )
    success_rate_node_min: float = Field(
        default=0.95, ge=0, le=1, description="Minimum node success rate"
    )
    success_rate_function_min: float = Field(
        default=0.90, ge=0, le=1, description="Minimum function success rate"
    )
    replicas_overload_threshold: int = Field(
        default=15, ge=1, description="Replica count overload threshold"
    )

    model_config = {"extra": "ignore"}


class DfaasLokiConfig(BaseModel):
    """Loki log shipping settings for DFaaS generator."""

    enabled: bool = Field(default=False, description="Enable Loki log push")
    endpoint: str = Field(
        default="http://localhost:3100",
        description="Loki base URL or push endpoint",
    )
    labels: dict[str, str] = Field(
        default_factory=dict, description="Static labels sent with Loki logs"
    )

    model_config = {"extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _apply_env_fallbacks(cls, values: Any) -> Any:
        """Apply env vars as fallbacks for missing config values.

        Priority: config file > environment variables > defaults.
        """
        values = _normalize_validator_values(values, cls)
        if not isinstance(values, dict):
            return values

        # Only apply env vars as fallbacks when config doesn't specify a value
        _set_env_bool(values, "enabled", "LB_LOKI_ENABLED")
        _set_env_str(values, "endpoint", "LB_LOKI_ENDPOINT")
        return values


class GrafanaConfig(BaseModel):
    """Optional Grafana integration settings."""

    enabled: bool = Field(default=False, description="Enable Grafana integration")
    url: str = Field(default="http://localhost:3000", description="Grafana base URL")
    api_key: str | None = Field(default=None, description="Grafana API key (optional)")
    org_id: int = Field(default=1, ge=1, description="Grafana organization id")

    model_config = {"extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _apply_env_fallbacks(cls, values: Any) -> Any:
        """Apply env vars as fallbacks for missing config values.

        Priority: config file > environment variables > defaults.
        """
        values = _normalize_validator_values(values, cls)
        if not isinstance(values, dict):
            return values

        # Only apply env vars as fallbacks when config doesn't specify a value
        _set_env_bool(values, "enabled", "LB_GRAFANA_ENABLED")
        _set_env_str(values, "url", "LB_GRAFANA_URL")
        _set_env_str(values, "api_key", "LB_GRAFANA_API_KEY")
        _set_env_int(values, "org_id", "LB_GRAFANA_ORG_ID")
        return values


class MemoryConfig(BaseModel):
    """In-process memory settings for PEVA-faas execution."""

    backend: Literal["duckdb"] = Field(
        default="duckdb", description="Memory backend type"
    )
    db_path: str = Field(
        default="benchmark_results/peva_faas/memory/peva_faas.duckdb",
        description="DuckDB path for persistent memory",
    )
    preload_core_parquet_dir: str | None = Field(
        default=None,
        description="Optional Parquet directory used to preload core memory tables",
    )
    export_core_parquet_dir: str | None = Field(
        default=None, description="Optional output directory for core Parquet exports"
    )
    export_raw_debug_parquet_dir: str | None = Field(
        default=None, description="Optional output directory for raw debug Parquet exports"
    )
    preload_raw_debug: bool = Field(
        default=False,
        description="Load raw debug summaries at startup (disabled by default)",
    )
    schema_version: str = Field(
        default="peva_faas_mem_v1", description="Strict schema version label"
    )

    model_config = {"extra": "ignore"}


class DfaasConfig(BasePluginConfig):
    """Configuration for PEVA-faas workload generation."""

    config_path: Path | None = Field(
        default=None,
        description="Path to YAML/JSON config with common + plugins.peva_faas sections",
    )
    output_dir: Path | None = Field(
        default=None,
        description="Optional output directory for DFaaS artifacts",
    )
    run_id: str | None = Field(default=None, description="Optional run identifier")
    k3s_host: str = Field(default="127.0.0.1", description="k3s/OpenFaaS host address")
    k3s_user: str = Field(default="ubuntu", description="SSH user for k3s host")
    k3s_ssh_key: str = Field(
        default="~/.ssh/id_rsa", description="SSH private key path for k3s host"
    )
    k3s_port: int = Field(
        default=22, ge=1, le=65535, description="SSH port for k3s host"
    )
    k6_host: str = Field(default="127.0.0.1", description="k6 host address")
    k6_user: str = Field(default="ubuntu", description="SSH user for k6 host")
    k6_ssh_key: str = Field(default="~/.ssh/id_rsa", description="SSH private key path")
    k6_port: int = Field(default=22, ge=1, le=65535, description="SSH port")
    k6_workspace_root: str = Field(
        default=_DEFAULT_K6_WORKSPACE_ROOT,
        description="Workspace root on k6 host",
    )
    k6_log_stream: bool = Field(
        default=True,
        description="Stream k6 log output via SSH while each config runs",
    )
    k6_outputs: list[str] = Field(
        default_factory=list,
        description=(
            "Optional k6 outputs passed via --out, e.g. "
            "'loki=http://<controller>:3100/loki/api/v1/push'"
        ),
    )
    k6_tags: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Additional k6 tags merged with run_id/component/workload/repetition"
        ),
    )
    openfaas_port: int = Field(
        default=31112, ge=1, le=65535, description="OpenFaaS gateway NodePort"
    )
    prometheus_port: int = Field(
        default=30411, ge=1, le=65535, description="Prometheus NodePort"
    )
    gateway_url: str = Field(
        default="http://127.0.0.1:31112", description="OpenFaaS gateway URL"
    )
    prometheus_url: str = Field(
        default="http://127.0.0.1:30411", description="Prometheus base URL"
    )
    functions: list[DfaasFunctionConfig] = Field(
        default_factory=lambda: [
            DfaasFunctionConfig(
                name="figlet",
                method="POST",
                body="Hello PEVA-faas!",
                headers={"Content-Type": "text/plain"},
            )
        ],
        min_length=1,
        description="OpenFaaS functions to invoke",
    )
    rate_strategy: RateStrategyUnion = Field(
        default_factory=LinearRateStrategy,
        description="Strategy for generating rate values to test",
    )
    rates: DfaasRatesConfig | None = Field(
        default=None,
        description=(
            "DEPRECATED: Use rate_strategy instead. Kept for backward compatibility."
        ),
    )
    combinations: DfaasCombinationConfig = Field(
        default_factory=DfaasCombinationConfig,
        description="Function combination configuration",
    )
    duration: str = Field(default="30s", description="k6 duration string")
    iterations: int = Field(default=3, ge=1, description="Iterations per configuration")
    selection_mode: Literal["online", "micro_batch"] = Field(
        default="online",
        description="Configuration selection mode for policy updates",
    )
    micro_batch_size: int = Field(
        default=8,
        ge=1,
        description="Number of configurations processed before a micro-batch update",
    )
    micro_batch_window_s: int = Field(
        default=30,
        ge=1,
        description="Maximum time window for micro-batch policy updates",
    )
    algorithm_entrypoint: str | None = Field(
        default=None,
        description="Optional module:class entrypoint for custom policy algorithm",
    )
    cooldown: DfaasCooldownConfig = Field(
        default_factory=DfaasCooldownConfig, description="Cooldown behavior"
    )
    overload: DfaasOverloadConfig = Field(
        default_factory=DfaasOverloadConfig, description="Overload thresholds"
    )
    queries_path: str = Field(
        default=_DEFAULT_QUERIES_PATH,
        description="Path to Prometheus queries file",
    )
    deploy_functions: bool = Field(
        default=True, description="Whether to deploy OpenFaaS store functions"
    )
    scaphandre_enabled: bool = Field(
        default=False, description="Enable Scaphandre power metrics"
    )
    function_pid_regexes: dict[str, str] = Field(
        default_factory=dict,
        description="Optional PID regex per function for Scaphandre queries",
    )
    grafana: GrafanaConfig = Field(
        default_factory=GrafanaConfig,
        description="Grafana integration settings",
    )
    loki: DfaasLokiConfig = Field(
        default_factory=DfaasLokiConfig,
        description="Loki log shipping settings",
    )
    memory: MemoryConfig = Field(
        default_factory=MemoryConfig,
        description="In-process memory configuration",
    )

    @model_validator(mode="before")
    @classmethod
    def _load_from_config_path(cls, values: Any) -> Any:
        if isinstance(values, cls):
            return values
        if not isinstance(values, dict):
            return values
        config_path = values.get("config_path")
        if not config_path:
            return values
        path = Path(config_path).expanduser()
        base_data = _load_config_data(path)
        overrides = dict(values)
        overrides.pop("config_path", None)
        merged = _deep_merge(base_data, overrides)
        merged["config_path"] = path
        return merged

    @field_validator("duration")
    @classmethod
    def _validate_duration(cls, value: str) -> str:
        duration = value.strip()
        match = _DURATION_RE.match(duration)
        if not match:
            raise ValueError("duration must match <number><unit>, e.g. 30s or 1m")
        if int(match.group("value")) <= 0:
            raise ValueError("duration must be > 0")
        return duration

    @model_validator(mode="after")
    def _migrate_legacy_rates(self) -> "DfaasConfig":
        """Migrate legacy 'rates' field to 'rate_strategy'."""
        if self.rates is not None:
            # Check if rate_strategy is still at default values
            is_default_strategy = (
                isinstance(self.rate_strategy, LinearRateStrategy)
                and self.rate_strategy.min_rate == 0
                and self.rate_strategy.max_rate == 200
                and self.rate_strategy.step == 10
            )
            if is_default_strategy:
                # Migrate legacy rates to rate_strategy
                self.rate_strategy = LinearRateStrategy(
                    min_rate=self.rates.min_rate,
                    max_rate=self.rates.max_rate,
                    step=self.rates.step,
                )
            warnings.warn(
                "The 'rates' field is deprecated. Use 'rate_strategy' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self

    @model_validator(mode="after")
    def _validate_functions(self) -> "DfaasConfig":
        names = [fn.name for fn in self.functions]
        if len(set(names)) != len(names):
            raise ValueError("functions names must be unique")
        # Get min_rate from strategy if it has one
        min_rate = getattr(self.rate_strategy, "min_rate", 0)
        for fn in self.functions:
            if fn.max_rate is not None and fn.max_rate < min_rate:
                raise ValueError(
                    f"functions[{fn.name}].max_rate must be >= rate_strategy.min_rate"
                )
        return self

    @model_validator(mode="after")
    def _validate_ports(self) -> "DfaasConfig":
        if self.openfaas_port == self.prometheus_port:
            raise ValueError(
                f"openfaas_port and prometheus_port must be different "
                f"(both set to {self.openfaas_port})"
            )
        if self.openfaas_port == self.k3s_port:
            raise ValueError(
                f"openfaas_port and k3s_port (SSH) must be different "
                f"(both set to {self.openfaas_port})"
            )
        return self

    @model_validator(mode="after")
    def _normalize_k6_workspace_root(self) -> "DfaasConfig":
        if self.k6_workspace_root != _DEFAULT_K6_WORKSPACE_ROOT:
            return self
        if self.k6_user == "root":
            self.k6_workspace_root = "/root/.peva_faas-k6"
        elif self.k6_user != "ubuntu":
            self.k6_workspace_root = f"/home/{self.k6_user}/.peva_faas-k6"
        return self

    @model_validator(mode="after")
    def _normalize_queries_path(self) -> "DfaasConfig":
        raw_path = Path(self.queries_path).expanduser()
        if raw_path.exists():
            self.queries_path = str(raw_path)
            return self
        fallback = Path(__file__).parent / "queries.yml"
        if fallback.exists() and _looks_like_default_queries_path(raw_path):
            # Handle configs materialized on another host with absolute paths.
            self.queries_path = str(fallback)
        return self
