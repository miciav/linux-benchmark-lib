"""DFaaS workload plugin."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from ...interface import BasePluginConfig, SimpleWorkloadPlugin
from .generator import DfaasGenerator

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


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_config_data(config_path: Path) -> dict[str, Any]:
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
        default="/var/lib/dfaas-k6", description="Workspace root on k6 host"
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


class DfaasPlugin(SimpleWorkloadPlugin):
    """Plugin definition for DFaaS."""

    NAME = "dfaas"
    DESCRIPTION = "DFaaS k6 + OpenFaaS workload"
    CONFIG_CLS = DfaasConfig
    GENERATOR_CLS = DfaasGenerator
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_target.yml"

    def export_results_to_csv(
        self,
        results: list[dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        functions = _collect_functions(results)
        if not functions:
            return []

        results_rows, skipped_rows, index_rows, summaries, metrics, scripts = (
            _collect_generator_rows(results)
        )

        paths: list[Path] = []
        results_path = output_dir / "results.csv"
        _write_csv(results_path, _results_header(functions), results_rows)
        paths.append(results_path)

        skipped_path = output_dir / "skipped.csv"
        _write_csv(skipped_path, _skipped_header(functions), skipped_rows)
        paths.append(skipped_path)

        index_path = output_dir / "index.csv"
        _write_index_csv(index_path, index_rows)
        paths.append(index_path)

        summary_dir = output_dir / "summaries"
        metrics_dir = output_dir / "metrics"
        scripts_dir = output_dir / "k6_scripts"
        summary_dir.mkdir(parents=True, exist_ok=True)
        metrics_dir.mkdir(parents=True, exist_ok=True)
        scripts_dir.mkdir(parents=True, exist_ok=True)

        for entry in summaries:
            rep = entry.get("repetition")
            config_id = entry["config_id"]
            iteration = entry["iteration"]
            summary_path = summary_dir / f"summary-{config_id}-iter{iteration}-rep{rep}.json"
            summary_path.write_text(json.dumps(entry["summary"], indent=2))
            paths.append(summary_path)

        for entry in metrics:
            rep = entry.get("repetition")
            config_id = entry["config_id"]
            iteration = entry["iteration"]
            metrics_path = metrics_dir / f"metrics-{config_id}-iter{iteration}-rep{rep}.csv"
            _write_csv(metrics_path, _metrics_header(functions), [entry["row"]])
            paths.append(metrics_path)

        for entry in scripts:
            script_path = scripts_dir / f"config-{entry['config_id']}.js"
            if not script_path.exists():
                script_path.write_text(entry["script"])
                paths.append(script_path)

        return paths


def _collect_functions(results: list[dict[str, Any]]) -> list[str]:
    for entry in results:
        gen = entry.get("generator_result") or {}
        functions = gen.get("dfaas_functions")
        if functions:
            return list(functions)
    return []


def _collect_generator_rows(
    results: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    results_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    scripts: list[dict[str, Any]] = []

    for entry in results:
        rep = entry.get("repetition")
        gen = entry.get("generator_result") or {}
        results_rows.extend(gen.get("dfaas_results", []))
        skipped_rows.extend(gen.get("dfaas_skipped", []))
        index_rows.extend(gen.get("dfaas_index", []))
        for summary in gen.get("dfaas_summaries", []):
            summary_with_rep = dict(summary)
            summary_with_rep["repetition"] = rep
            summaries.append(summary_with_rep)
        for metric in gen.get("dfaas_metrics", []):
            metric_row = _flatten_metrics(metric.get("metrics", {}))
            metrics.append(
                {
                    "config_id": metric.get("config_id"),
                    "iteration": metric.get("iteration"),
                    "repetition": rep,
                    "row": metric_row,
                }
            )
        scripts.extend(gen.get("dfaas_scripts", []))

    return (
        results_rows,
        skipped_rows,
        _dedupe_index_rows(index_rows),
        summaries,
        metrics,
        scripts,
    )


def _dedupe_index_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[str, ...], tuple[int, ...]]] = set()
    output: list[dict[str, Any]] = []
    for row in rows:
        functions = tuple(row.get("functions", []))
        rates = tuple(row.get("rates", []))
        key = (functions, rates)
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _results_header(functions: list[str]) -> list[str]:
    header: list[str] = []
    for name in functions:
        header.extend(
            [
                f"function_{name}",
                f"rate_function_{name}",
                f"success_rate_function_{name}",
                f"cpu_usage_function_{name}",
                f"ram_usage_function_{name}",
                f"power_usage_function_{name}",
                f"replica_{name}",
                f"overloaded_function_{name}",
                f"medium_latency_function_{name}",
            ]
        )
    header.extend(
        [
            "cpu_usage_idle_node",
            "cpu_usage_node",
            "ram_usage_idle_node",
            "ram_usage_node",
            "ram_usage_idle_node_percentage",
            "ram_usage_node_percentage",
            "power_usage_idle_node",
            "power_usage_node",
            "rest_seconds",
            "overloaded_node",
        ]
    )
    return header


def _skipped_header(functions: list[str]) -> list[str]:
    header: list[str] = []
    for name in functions:
        header.extend([f"function_{name}", f"rate_function_{name}"])
    return header


def _metrics_header(functions: list[str]) -> list[str]:
    header = [
        "cpu_usage_node",
        "ram_usage_node",
        "ram_usage_node_pct",
        "power_usage_node",
    ]
    for name in functions:
        header.extend(
            [
                f"cpu_usage_function_{name}",
                f"ram_usage_function_{name}",
                f"power_usage_function_{name}",
            ]
        )
    return header


def _flatten_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "cpu_usage_node": metrics.get("cpu_usage_node", "nan"),
        "ram_usage_node": metrics.get("ram_usage_node", "nan"),
        "ram_usage_node_pct": metrics.get("ram_usage_node_pct", "nan"),
        "power_usage_node": metrics.get("power_usage_node", "nan"),
    }
    for name, values in (metrics.get("functions", {}) or {}).items():
        row[f"cpu_usage_function_{name}"] = values.get("cpu", "nan")
        row[f"ram_usage_function_{name}"] = values.get("ram", "nan")
        row[f"power_usage_function_{name}"] = values.get("power", "nan")
    return row


def _write_csv(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_index_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["functions", "rates", "results_file"])
        for row in rows:
            writer.writerow(
                [
                    row.get("functions", []),
                    row.get("rates", []),
                    row.get("results_file", "results.csv"),
                ]
            )


PLUGIN = DfaasPlugin()
