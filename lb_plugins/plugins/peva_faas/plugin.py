"""PEVA-faas workload plugin."""

from __future__ import annotations

import csv
from importlib import import_module
import json
from pathlib import Path
from typing import Any

from ...interface import BasePluginConfig, SimpleWorkloadPlugin
from .config import DfaasConfig
from .grafana_assets import GRAFANA_ASSETS


class DfaasPlugin(SimpleWorkloadPlugin):
    """Plugin definition for PEVA-faas."""

    NAME = "peva_faas"
    DESCRIPTION = "PEVA-faas k6 + OpenFaaS workload"
    REQUIRED_UV_EXTRAS = ["peva_faas"]
    CONFIG_CLS = DfaasConfig
    GENERATOR_CLS = None
    SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"
    COLLECT_PRE_PLAYBOOK = Path(__file__).parent / "ansible" / "collect" / "pre.yml"
    COLLECT_POST_PLAYBOOK = Path(__file__).parent / "ansible" / "collect" / "post.yml"
    GRAFANA_ASSETS = GRAFANA_ASSETS

    def create_generator(self, config: BasePluginConfig) -> Any:
        generator_cls = import_module(
            "lb_plugins.plugins.peva_faas.generator"
        ).DfaasGenerator
        return generator_cls(config)

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
            summary_name = f"summary-{config_id}-iter{iteration}-rep{rep}.json"
            summary_path = summary_dir / summary_name
            summary_path.write_text(json.dumps(entry["summary"], indent=2))
            paths.append(summary_path)

        for entry in metrics:
            rep = entry.get("repetition")
            config_id = entry["config_id"]
            iteration = entry["iteration"]
            metrics_name = f"metrics-{config_id}-iter{iteration}-rep{rep}.csv"
            metrics_path = metrics_dir / metrics_name
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
        functions = gen.get("peva_faas_functions")
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
        results_rows.extend(gen.get("peva_faas_results", []))
        skipped_rows.extend(gen.get("peva_faas_skipped", []))
        index_rows.extend(gen.get("peva_faas_index", []))
        for summary in gen.get("peva_faas_summaries", []):
            summary_with_rep = dict(summary)
            summary_with_rep["repetition"] = rep
            summaries.append(summary_with_rep)
        for metric in gen.get("peva_faas_metrics", []):
            metric_row = _flatten_metrics(metric.get("metrics", {}))
            metrics.append(
                {
                    "config_id": metric.get("config_id"),
                    "iteration": metric.get("iteration"),
                    "repetition": rep,
                    "row": metric_row,
                }
            )
        scripts.extend(gen.get("peva_faas_scripts", []))

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
