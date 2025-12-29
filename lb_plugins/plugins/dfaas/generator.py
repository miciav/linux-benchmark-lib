from __future__ import annotations

import ast
import csv
import hashlib
import json
import logging
import os
import math
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from typing import TYPE_CHECKING
from .queries import (
    PrometheusQueryError,
    PrometheusQueryRunner,
    QueryDefinition,
    filter_queries,
    load_queries,
)
from ...base_generator import BaseGenerator

if TYPE_CHECKING:
    from .plugin import DfaasConfig

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^(?P<value>[0-9]+)(?P<unit>ms|s|m|h)$")


@dataclass(frozen=True)
class MetricsSnapshot:
    cpu: float
    ram: float
    ram_pct: float
    power: float


def _parse_duration_seconds(duration: str) -> int:
    match = _DURATION_RE.match(duration.strip())
    if not match:
        raise ValueError(f"Invalid duration format: {duration!r}")
    value = int(match.group("value"))
    unit = match.group("unit")
    if unit == "ms":
        return max(1, int(value / 1000))
    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    raise ValueError(f"Unsupported duration unit: {unit}")


def _normalize_metric_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned:
        cleaned = "fn"
    if cleaned[0].isdigit():
        cleaned = f"fn_{cleaned}"
    return cleaned


def generate_rates_list(min_rate: int, max_rate: int, step: int) -> list[int]:
    return list(range(min_rate, max_rate + 1, step))


def generate_function_combinations(
    functions: list[str], min_functions: int, max_functions: int
) -> list[tuple[str, ...]]:
    from itertools import combinations

    sorted_functions = sorted(functions)
    combos: list[tuple[str, ...]] = []
    for size in range(min_functions, max_functions):
        combos.extend(combinations(sorted_functions, size))
    return combos


def generate_configurations(
    functions: list[str],
    rates: list[int],
    min_functions: int,
    max_functions: int,
    rates_by_function: dict[str, list[int]] | None = None,
) -> list[list[tuple[str, int]]]:
    from itertools import product

    configs: list[list[tuple[str, int]]] = []
    combos = generate_function_combinations(functions, min_functions, max_functions)
    for combo in combos:
        rate_sets: list[list[tuple[str, int]]] = []
        for fn in combo:
            fn_rates = rates_by_function.get(fn, rates) if rates_by_function else rates
            rate_sets.append([(fn, rate) for rate in fn_rates])
        for selection in product(*rate_sets):
            configs.append(list(selection))
    return configs


def config_key(config: Iterable[tuple[str, int]]) -> tuple[tuple[str, ...], tuple[int, ...]]:
    sorted_config = sorted(config, key=lambda pair: pair[0])
    names = tuple(fn for fn, _ in sorted_config)
    rates = tuple(rate for _, rate in sorted_config)
    return names, rates


def config_id(config: Iterable[tuple[str, int]]) -> str:
    names, rates = config_key(config)
    payload = "|".join(f"{name}:{rate}" for name, rate in zip(names, rates))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def dominates(
    base_config: Iterable[tuple[str, int]] | None,
    candidate_config: Iterable[tuple[str, int]],
) -> bool:
    if base_config is None:
        return False
    base_names, base_rates = config_key(base_config)
    candidate_names, candidate_rates = config_key(candidate_config)
    if base_names != candidate_names:
        return False
    better = False
    for base_rate, candidate_rate in zip(base_rates, candidate_rates):
        if candidate_rate < base_rate:
            return False
        if candidate_rate > base_rate:
            better = True
    return better


def build_k6_script(
    config: DfaasConfig,
    config_pairs: list[tuple[str, int]],
) -> tuple[str, dict[str, str]]:
    functions_by_name = {fn.name: fn for fn in config.functions}
    metric_ids: dict[str, str] = {}
    lines: list[str] = [
        'import http from "k6/http";',
        'import { check, sleep } from "k6";',
        'import { Rate, Trend, Counter } from "k6/metrics";',
        "",
    ]

    scenarios: list[str] = []
    for name, rate in sorted(config_pairs, key=lambda pair: pair[0]):
        fn_cfg = functions_by_name[name]
        metric_id = _normalize_metric_id(name)
        if metric_id in metric_ids.values():
            metric_id = f"{metric_id}_{len(metric_ids) + 1}"
        metric_ids[name] = metric_id

        body = json.dumps(fn_cfg.body)
        headers = json.dumps(fn_cfg.headers)
        url = f"{config.gateway_url.rstrip('/')}/function/{name}"
        exec_name = f"exec_{metric_id}"

        lines.extend(
            [
                f'const fn_{metric_id} = {{',
                f'  method: "{fn_cfg.method}",',
                f'  url: "{url}",',
                f"  body: {body},",
                f"  headers: {headers},",
                "};",
                f'const success_rate_{metric_id} = new Rate("success_rate_{metric_id}");',
                f'const latency_{metric_id} = new Trend("latency_{metric_id}");',
                f'const request_count_{metric_id} = new Counter("request_count_{metric_id}");',
                "",
                f"export function {exec_name}() {{",
                f"  const res = http.request(fn_{metric_id}.method, fn_{metric_id}.url, fn_{metric_id}.body, {{ headers: fn_{metric_id}.headers }});",
                "  const ok = res.status >= 200 && res.status < 300;",
                f"  success_rate_{metric_id}.add(ok);",
                f"  latency_{metric_id}.add(res.timings.duration);",
                f"  request_count_{metric_id}.add(1);",
                '  check(res, { "status is 2xx": (r) => r.status >= 200 && r.status < 300 });',
                "}",
                "",
            ]
        )

        if rate > 0:
            vus = max(1, rate)
            scenarios.append(
                "\n".join(
                    [
                        f'    {metric_id}: {{',
                        '      executor: "constant-arrival-rate",',
                        f"      rate: {rate},",
                        '      timeUnit: "1s",',
                        f'      duration: "{config.duration}",',
                        f"      preAllocatedVUs: {vus},",
                        f"      maxVUs: {vus},",
                        f'      exec: "{exec_name}",',
                        f'      tags: {{ function: "{name}" }},',
                        "    },",
                    ]
                )
            )

    lines.append("export const options = {")
    lines.append("  scenarios: {")
    if scenarios:
        lines.extend(scenarios)
    else:
        lines.extend(
            [
                '    idle: {',
                '      executor: "constant-vus",',
                "      vus: 1,",
                f'      duration: "{config.duration}",',
                '      exec: "idle_exec",',
                "    },",
            ]
        )
    lines.append("  },")
    lines.append("};")
    lines.append("")

    if not scenarios:
        lines.extend(
            [
                "export function idle_exec() {",
                "  sleep(1);",
                "}",
                "",
            ]
        )

    return "\n".join(lines), metric_ids


def parse_k6_summary(
    summary: dict[str, Any], metric_ids: dict[str, str]
) -> dict[str, dict[str, float]]:
    metrics = summary.get("metrics", {}) or {}
    parsed: dict[str, dict[str, float]] = {}
    for name, metric_id in metric_ids.items():
        success_metric = metrics.get(f"success_rate_{metric_id}", {}).get("values", {})
        latency_metric = metrics.get(f"latency_{metric_id}", {}).get("values", {})
        count_metric = metrics.get(f"request_count_{metric_id}", {}).get("values", {})

        success_rate = float(success_metric.get("rate", 1.0))
        latency_avg = float(latency_metric.get("avg", 0.0))
        request_count = float(count_metric.get("count", count_metric.get("rate", 0.0)))

        parsed[name] = {
            "success_rate": success_rate,
            "avg_latency": latency_avg,
            "request_count": request_count,
        }
    return parsed


class DfaasGenerator(BaseGenerator):
    """DFaaS generator that orchestrates one config at a time."""

    def __init__(self, config: DfaasConfig, name: str = "DfaasGenerator"):
        super().__init__(name)
        self.config = config
        self.expected_runtime_seconds = self._estimate_runtime()

    def _estimate_runtime(self) -> int:
        duration = _parse_duration_seconds(self.config.duration)
        rates = generate_rates_list(
            self.config.rates.min_rate,
            self.config.rates.max_rate,
            self.config.rates.step,
        )
        rates_by_function = self._build_rates_by_function(rates)
        configs = generate_configurations(
            [fn.name for fn in self.config.functions],
            rates,
            self.config.combinations.min_functions,
            self.config.combinations.max_functions,
            rates_by_function=rates_by_function,
        )
        return max(1, duration * max(1, self.config.iterations) * max(1, len(configs)))

    def _validate_environment(self) -> bool:
        required = ["ansible-playbook", "faas-cli"]
        for tool in required:
            if subprocess.run(["which", tool], capture_output=True).returncode != 0:
                logger.error("Required tool missing: %s", tool)
                return False
        if self.config.k6_ssh_key and not Path(self.config.k6_ssh_key).expanduser().exists():
            logger.error("k6_ssh_key does not exist: %s", self.config.k6_ssh_key)
            return False
        return True

    def _stop_workload(self) -> None:
        return None

    def _run_command(self) -> None:
        output_dir = self._resolve_output_dir()
        function_names = sorted(fn.name for fn in self.config.functions)
        rates = generate_rates_list(
            self.config.rates.min_rate,
            self.config.rates.max_rate,
            self.config.rates.step,
        )
        rates_by_function = self._build_rates_by_function(rates)
        configs = generate_configurations(
            function_names,
            rates,
            self.config.combinations.min_functions,
            self.config.combinations.max_functions,
            rates_by_function=rates_by_function,
        )

        queries = load_queries(Path(self.config.queries_path))
        active_queries = filter_queries(
            queries, scaphandre_enabled=self.config.scaphandre_enabled
        )
        queries_by_name = {query.name: query for query in active_queries}
        runner = PrometheusQueryRunner(self.config.prometheus_url)

        existing_index = self._load_index(output_dir)
        results_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        index_rows: list[dict[str, Any]] = []
        summary_entries: list[dict[str, Any]] = []
        metrics_entries: list[dict[str, Any]] = []
        script_entries: list[dict[str, Any]] = []
        overloaded_configs: list[list[tuple[str, int]]] = []

        base_idle = self._query_node_metrics(runner, queries_by_name, None, None)

        for config_pairs in configs:
            if any(dominates(over, config_pairs) for over in overloaded_configs):
                skipped_rows.append(self._build_skipped_row(function_names, config_pairs))
                continue
            key = config_key(config_pairs)
            if key in existing_index:
                skipped_rows.append(self._build_skipped_row(function_names, config_pairs))
                continue

            cfg_id = config_id(config_pairs)
            script, metric_ids = build_k6_script(self.config, config_pairs)
            script_entries.append({"config_id": cfg_id, "script": script})

            overload_counter = 0
            try:
                for iteration in range(1, self.config.iterations + 1):
                    idle_snapshot, rest_seconds = self._cooldown(
                        runner,
                        queries_by_name,
                        base_idle,
                        function_names,
                    )
                    start_time = time.time()
                    summary_data = self._run_k6(cfg_id, script)
                    end_time = time.time()

                    summary_metrics = parse_k6_summary(summary_data, metric_ids)
                    replicas = self._get_function_replicas(function_names)
                    metrics = self._query_metrics(
                        runner,
                        queries_by_name,
                        config_pairs,
                        start_time,
                        end_time,
                    )
                    row, overloaded = self._build_result_row(
                        function_names,
                        config_pairs,
                        summary_metrics,
                        replicas,
                        metrics,
                        idle_snapshot,
                        rest_seconds,
                    )
                    results_rows.append(row)
                    metrics_entries.append(
                        {
                            "config_id": cfg_id,
                            "iteration": iteration,
                            "metrics": metrics,
                        }
                    )
                    summary_entries.append(
                        {
                            "config_id": cfg_id,
                            "iteration": iteration,
                            "summary": summary_data,
                        }
                    )
                    if overloaded:
                        overload_counter += 1

                if overload_counter > self.config.iterations / 2:
                    overloaded_configs.append(list(config_pairs))
                index_rows.append(
                    {
                        "functions": list(key[0]),
                        "rates": list(key[1]),
                        "results_file": "results.csv",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed config %s: %s", cfg_id, exc)
                skipped_rows.append(self._build_skipped_row(function_names, config_pairs))

        self._result = {
            "returncode": 0,
            "success": True,
            "dfaas_functions": function_names,
            "dfaas_results": results_rows,
            "dfaas_skipped": skipped_rows,
            "dfaas_index": index_rows,
            "dfaas_summaries": summary_entries,
            "dfaas_metrics": metrics_entries,
            "dfaas_scripts": script_entries,
        }

    def _build_rates_by_function(self, rates: list[int]) -> dict[str, list[int]]:
        rates_by_function: dict[str, list[int]] = {}
        for fn in self.config.functions:
            if fn.max_rate is None:
                continue
            rates_by_function[fn.name] = [rate for rate in rates if rate <= fn.max_rate]
        return rates_by_function

    def _resolve_output_dir(self) -> Path:
        if self.config.output_dir:
            return Path(self.config.output_dir).expanduser()
        cfg_path = Path("benchmark_config.generated.json")
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text())
                output_root = Path(data.get("output_dir", "."))
                workloads = data.get("workloads", {})
                workload_name = "dfaas"
                for name, entry in workloads.items():
                    if isinstance(entry, dict) and entry.get("plugin") == "dfaas":
                        workload_name = name
                        break
                return output_root / workload_name
            except Exception:  # noqa: BLE001
                pass
        return Path.cwd() / "benchmark_results" / "dfaas"

    def _load_index(
        self, output_dir: Path
    ) -> set[tuple[tuple[str, ...], tuple[int, ...]]]:
        index_path = output_dir / "index.csv"
        if not index_path.exists():
            return set()
        try:
            with index_path.open("r") as handle:
                reader = csv.DictReader(handle, delimiter=";")
                entries = set()
                for row in reader:
                    functions = ast.literal_eval(row.get("functions", "[]"))
                    rates = ast.literal_eval(row.get("rates", "[]"))
                    entries.add((tuple(functions), tuple(rates)))
                return entries
        except Exception:  # noqa: BLE001
            return set()

    def _cooldown(
        self,
        runner: PrometheusQueryRunner,
        queries: dict[str, QueryDefinition],
        base_idle: MetricsSnapshot,
        function_names: list[str],
    ) -> tuple[MetricsSnapshot, int]:
        max_wait = self.config.cooldown.max_wait_seconds
        sleep_step = self.config.cooldown.sleep_step_seconds
        threshold_pct = self.config.cooldown.idle_threshold_pct / 100.0
        waited = 0

        while True:
            snapshot = self._query_node_metrics(runner, queries, None, None)
            replicas = self._get_function_replicas(function_names)
            replicas_ok = all(value < 2 for value in replicas.values())
            if (
                _within_threshold(snapshot.cpu, base_idle.cpu, threshold_pct)
                and _within_threshold(snapshot.ram, base_idle.ram, threshold_pct)
                and _within_threshold(snapshot.power, base_idle.power, threshold_pct)
                and replicas_ok
            ):
                return snapshot, waited
            time.sleep(sleep_step)
            waited += sleep_step
            if waited > max_wait:
                raise TimeoutError("Cooldown exceeded max_wait_seconds")

    def _query_node_metrics(
        self,
        runner: PrometheusQueryRunner,
        queries: dict[str, QueryDefinition],
        start_time: float | None,
        end_time: float | None,
    ) -> MetricsSnapshot:
        duration = self.config.duration
        cpu = runner.execute(
            queries["cpu_usage_node"],
            time_span=duration,
            start_time=start_time,
            end_time=end_time,
        )
        ram = runner.execute(
            queries["ram_usage_node"],
            time_span=duration,
            start_time=start_time,
            end_time=end_time,
        )
        ram_pct = runner.execute(
            queries["ram_usage_node_pct"],
            time_span=duration,
            start_time=start_time,
            end_time=end_time,
        )
        power = float("nan")
        if self.config.scaphandre_enabled and "power_usage_node" in queries:
            power = runner.execute(
                queries["power_usage_node"],
                time_span=duration,
                start_time=start_time,
                end_time=end_time,
            )
        return MetricsSnapshot(cpu=cpu, ram=ram, ram_pct=ram_pct, power=power)

    def _query_metrics(
        self,
        runner: PrometheusQueryRunner,
        queries: dict[str, QueryDefinition],
        config_pairs: list[tuple[str, int]],
        start_time: float,
        end_time: float,
    ) -> dict[str, Any]:
        duration = self.config.duration
        range_query = end_time - start_time > _parse_duration_seconds(duration)
        start = start_time if range_query else None
        end = end_time if range_query else None

        node = self._query_node_metrics(runner, queries, start, end)
        metrics: dict[str, Any] = {
            "cpu_usage_node": node.cpu,
            "ram_usage_node": node.ram,
            "ram_usage_node_pct": node.ram_pct,
            "power_usage_node": node.power,
            "functions": {},
        }

        for name, _ in config_pairs:
            function_metrics = {}
            try:
                function_metrics["cpu"] = runner.execute(
                    queries["cpu_usage_function"],
                    time_span=duration,
                    start_time=start,
                    end_time=end,
                    function_name=name,
                )
                function_metrics["ram"] = runner.execute(
                    queries["ram_usage_function"],
                    time_span=duration,
                    start_time=start,
                    end_time=end,
                    function_name=name,
                )
                function_metrics["power"] = float("nan")
                if (
                    self.config.scaphandre_enabled
                    and "power_usage_function" in queries
                ):
                    pid_regex = self.config.function_pid_regexes.get(name)
                    if pid_regex:
                        function_metrics["power"] = runner.execute(
                            queries["power_usage_function"],
                            time_span=duration,
                            start_time=start,
                            end_time=end,
                            pid_regex=pid_regex,
                        )
            except PrometheusQueryError as exc:
                logger.warning("Prometheus query failed for %s: %s", name, exc)
                function_metrics["cpu"] = float("nan")
                function_metrics["ram"] = float("nan")
                function_metrics["power"] = float("nan")
            metrics["functions"][name] = function_metrics
        return metrics

    def _build_result_row(
        self,
        all_functions: list[str],
        config_pairs: list[tuple[str, int]],
        summary_metrics: dict[str, dict[str, float]],
        replicas: dict[str, int],
        metrics: dict[str, Any],
        idle_snapshot: MetricsSnapshot,
        rest_seconds: int,
    ) -> tuple[dict[str, Any], bool]:
        row: dict[str, Any] = {}
        config_map = {name: rate for name, rate in config_pairs}
        overloaded_any = False
        avg_success_rate = 0.0
        present_count = 0

        for name in all_functions:
            if name in config_map:
                success = summary_metrics.get(name, {}).get("success_rate", 1.0)
                latency = summary_metrics.get(name, {}).get("avg_latency", 0.0)
                cpu = metrics["functions"].get(name, {}).get("cpu", float("nan"))
                ram = metrics["functions"].get(name, {}).get("ram", float("nan"))
                power = metrics["functions"].get(name, {}).get("power", float("nan"))
                replica = int(replicas.get(name, 0))
                overloaded_function = int(
                    success < self.config.overload.success_rate_function_min
                    or replica >= self.config.overload.replicas_overload_threshold
                )
                if overloaded_function:
                    overloaded_any = True
                avg_success_rate += success
                present_count += 1

                row[f"function_{name}"] = name
                row[f"rate_function_{name}"] = config_map[name]
                row[f"success_rate_function_{name}"] = _format_float(success)
                row[f"cpu_usage_function_{name}"] = _format_float(cpu)
                row[f"ram_usage_function_{name}"] = _format_float(ram)
                row[f"power_usage_function_{name}"] = _format_float(power)
                row[f"replica_{name}"] = replica
                row[f"overloaded_function_{name}"] = overloaded_function
                row[f"medium_latency_function_{name}"] = int(latency)
            else:
                row[f"function_{name}"] = ""
                row[f"rate_function_{name}"] = ""
                row[f"success_rate_function_{name}"] = ""
                row[f"cpu_usage_function_{name}"] = ""
                row[f"ram_usage_function_{name}"] = ""
                row[f"power_usage_function_{name}"] = ""
                row[f"replica_{name}"] = ""
                row[f"overloaded_function_{name}"] = ""
                row[f"medium_latency_function_{name}"] = ""

        avg_success_rate = (
            avg_success_rate / present_count if present_count else 1.0
        )
        node_cpu = float(metrics.get("cpu_usage_node", float("nan")))
        node_ram = float(metrics.get("ram_usage_node", float("nan")))
        node_ram_pct = float(metrics.get("ram_usage_node_pct", float("nan")))
        node_power = float(metrics.get("power_usage_node", float("nan")))

        overloaded_node = int(
            avg_success_rate < self.config.overload.success_rate_node_min
            or node_cpu > self.config.overload.cpu_overload_pct_of_capacity
            or node_ram_pct > self.config.overload.ram_overload_pct
            or overloaded_any
        )

        row["cpu_usage_idle_node"] = _format_float(idle_snapshot.cpu)
        row["cpu_usage_node"] = _format_float(node_cpu)
        row["ram_usage_idle_node"] = _format_float(idle_snapshot.ram)
        row["ram_usage_node"] = _format_float(node_ram)
        row["ram_usage_idle_node_percentage"] = _format_float(idle_snapshot.ram_pct)
        row["ram_usage_node_percentage"] = _format_float(node_ram_pct)
        row["power_usage_idle_node"] = _format_float(idle_snapshot.power)
        row["power_usage_node"] = _format_float(node_power)
        row["rest_seconds"] = rest_seconds
        row["overloaded_node"] = overloaded_node

        return row, bool(overloaded_node)

    def _build_skipped_row(
        self, all_functions: list[str], config_pairs: list[tuple[str, int]]
    ) -> dict[str, Any]:
        row: dict[str, Any] = {}
        config_map = {name: rate for name, rate in config_pairs}
        for name in all_functions:
            if name in config_map:
                row[f"function_{name}"] = name
                row[f"rate_function_{name}"] = config_map[name]
            else:
                row[f"function_{name}"] = ""
                row[f"rate_function_{name}"] = ""
        return row

    def _get_function_replicas(self, function_names: list[str]) -> dict[str, int]:
        replicas = {name: 0 for name in function_names}
        cmd = [
            "faas-cli",
            "list",
            "--gateway",
            self.config.gateway_url,
            "--tls-no-verify",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as exc:
            logger.error("faas-cli list failed: %s", exc)
            return replicas

        lines = result.stdout.strip().splitlines()
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            name, _, replica = parts[0], parts[1], parts[2]
            if name in replicas:
                try:
                    replicas[name] = int(replica)
                except ValueError:
                    replicas[name] = 0
        return replicas

    def _run_k6(self, config_id_value: str, script: str) -> dict[str, Any]:
        playbook = Path(__file__).parent / "ansible" / "run_k6.yml"
        if not playbook.exists():
            raise FileNotFoundError(f"Missing playbook: {playbook}")

        target_name = os.environ.get("LB_RUN_HOST") or os.uname().nodename
        run_id = self._resolve_run_id()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            script_path = temp_path / f"config-{config_id_value}.js"
            script_path.write_text(script)
            summary_path = temp_path / "summary.json"
            inventory_path = temp_path / "inventory.ini"
            inventory_path.write_text(
                "\n".join(
                    [
                        "[k6]",
                        (
                            f"k6_host ansible_host={self.config.k6_host} "
                            f"ansible_user={self.config.k6_user} "
                            f"ansible_port={self.config.k6_port} "
                            f"ansible_ssh_private_key_file={Path(self.config.k6_ssh_key).expanduser()} "
                            "ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'"
                        ),
                        "",
                    ]
                )
            )

            cmd = [
                "ansible-playbook",
                "-i",
                str(inventory_path),
                str(playbook),
                "-e",
                f"target_name={target_name}",
                "-e",
                f"run_id={run_id}",
                "-e",
                f"config_id={config_id_value}",
                "-e",
                f"script_src={script_path}",
                "-e",
                f"summary_fetch_dest={temp_path}/",
                "-e",
                f"k6_workspace_root={self.config.k6_workspace_root}",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"k6 playbook failed: {result.stdout}\n{result.stderr}"
                )
            return json.loads(summary_path.read_text())

    def _resolve_run_id(self) -> str:
        if self.config.run_id:
            return self.config.run_id
        cfg_path = Path("benchmark_config.generated.json")
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text())
                output_dir = Path(data.get("output_dir", "."))
                return output_dir.parent.name
            except Exception:  # noqa: BLE001
                pass
        return f"run-{int(time.time())}"


def _within_threshold(value: float, baseline: float, threshold_pct: float) -> bool:
    if math.isnan(baseline) or math.isnan(value):
        return True
    return value <= baseline + (baseline * threshold_pct)


def _format_float(value: float) -> str:
    if math.isnan(value):
        return "nan"
    return f"{value:.3f}"
