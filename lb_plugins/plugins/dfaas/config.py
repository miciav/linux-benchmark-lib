"""DFaaS configuration models."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from lb_common.api import parse_bool_env, parse_int_env

from ...interface import BasePluginConfig

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
_DEFAULT_K6_WORKSPACE_ROOT = "/home/ubuntu/.dfaas-k6"


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two dictionaries."""
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_config_data(config_path: Path) -> dict[str, Any]:
    """Load and merge config from YAML file."""
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    data = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a mapping at the top level.")
    common = data.get("common", {}) or {}
    plugin_data = data.get("plugins", {}).get("dfaas", {}) or {}
    if not isinstance(common, dict) or not isinstance(plugin_data, dict):
        raise ValueError("Config sections 'common' and 'plugins.dfaas' must be mappings.")
    return _deep_merge(common, plugin_data)


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
    """Rate list configuration (inclusive range)."""

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
    max_functions: int = Field(default=2, ge=1, description="Maximum functions (exclusive)")

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _validate_bounds(self) -> "DfaasCombinationConfig":
        if self.max_functions <= self.min_functions:
            raise ValueError("combinations.max_functions must be > combinations.min_functions")
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


class GrafanaConfig(BaseModel):
    """Optional Grafana integration settings."""

    enabled: bool = Field(default=False, description="Enable Grafana integration")
    url: str = Field(default="http://localhost:3000", description="Grafana base URL")
    api_key: str | None = Field(default=None, description="Grafana API key (optional)")
    org_id: int = Field(default=1, ge=1, description="Grafana organization id")

    model_config = {"extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _apply_env_overrides(cls, values: Any) -> Any:
        if isinstance(values, cls):
            return values
        if values is None:
            values = {}
        if not isinstance(values, dict):
            return values

        env_enabled = parse_bool_env(os.environ.get("LB_GRAFANA_ENABLED"))
        env_url = os.environ.get("LB_GRAFANA_URL")
        env_api_key = os.environ.get("LB_GRAFANA_API_KEY")
        env_org = parse_int_env(os.environ.get("LB_GRAFANA_ORG_ID"))

        if env_enabled is not None:
            values["enabled"] = env_enabled
        if env_url:
            values["url"] = env_url
        if env_api_key:
            values["api_key"] = env_api_key
        if env_org is not None:
            values["org_id"] = env_org

        return values


class DfaasConfig(BasePluginConfig):
    """Configuration for DFaaS workload generation."""

    config_path: Path | None = Field(
        default=None,
        description="Path to YAML/JSON config with common + plugins.dfaas sections",
    )
    output_dir: Path | None = Field(
        default=None,
        description="Optional output directory for DFaaS artifacts",
    )
    run_id: str | None = Field(default=None, description="Optional run identifier")
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
        description="Additional k6 tags merged with run_id/component/workload/repetition",
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
                body="Hello DFaaS!",
                headers={"Content-Type": "text/plain"},
            )
        ],
        min_length=1,
        description="OpenFaaS functions to invoke",
    )
    rates: DfaasRatesConfig = Field(
        default_factory=DfaasRatesConfig, description="Rate list configuration"
    )
    combinations: DfaasCombinationConfig = Field(
        default_factory=DfaasCombinationConfig,
        description="Function combination configuration",
    )
    duration: str = Field(default="30s", description="k6 duration string")
    iterations: int = Field(default=3, ge=1, description="Iterations per configuration")
    cooldown: DfaasCooldownConfig = Field(
        default_factory=DfaasCooldownConfig, description="Cooldown behavior"
    )
    overload: DfaasOverloadConfig = Field(
        default_factory=DfaasOverloadConfig, description="Overload thresholds"
    )
    queries_path: str = Field(
        default="lb_plugins/plugins/dfaas/queries.yml",
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
    def _validate_functions(self) -> "DfaasConfig":
        names = [fn.name for fn in self.functions]
        if len(set(names)) != len(names):
            raise ValueError("functions names must be unique")
        for fn in self.functions:
            if fn.max_rate is not None and fn.max_rate < self.rates.min_rate:
                raise ValueError(
                    f"functions[{fn.name}].max_rate must be >= rates.min_rate"
                )
        return self

    @model_validator(mode="after")
    def _validate_ports(self) -> "DfaasConfig":
        if self.openfaas_port == self.prometheus_port:
            raise ValueError(
                f"openfaas_port and prometheus_port must be different "
                f"(both set to {self.openfaas_port})"
            )
        if self.openfaas_port == self.k6_port:
            raise ValueError(
                f"openfaas_port and k6_port (SSH) must be different "
                f"(both set to {self.openfaas_port})"
            )
        return self

    @model_validator(mode="after")
    def _normalize_k6_workspace_root(self) -> "DfaasConfig":
        if self.k6_workspace_root != _DEFAULT_K6_WORKSPACE_ROOT:
            return self
        if self.k6_user == "root":
            self.k6_workspace_root = "/root/.dfaas-k6"
        elif self.k6_user != "ubuntu":
            self.k6_workspace_root = f"/home/{self.k6_user}/.dfaas-k6"
        return self
