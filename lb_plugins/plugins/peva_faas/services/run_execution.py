from __future__ import annotations

import ast
import csv
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import DfaasConfig
from ..context import ExecutionContext
from ..exceptions import K6ExecutionError
from .annotation_service import DfaasAnnotationService
from .cooldown import CooldownManager, CooldownTimeoutError, MetricsSnapshot
from .log_manager import DfaasLogManager
from .metrics_collector import MetricsCollector
from .plan_builder import DfaasPlanBuilder, config_id, config_key, dominates
from .result_builder import DfaasResultBuilder
from .k6_runner import K6Runner

logger = logging.getLogger(__name__)


@dataclass
class DfaasRunContext:
    """Context object holding state for a benchmark run."""

    function_names: list[str]
    configs: list[list[tuple[str, int]]]
    existing_index: set[tuple[tuple[str, ...], tuple[int, ...]]]
    cooldown_manager: CooldownManager
    base_idle: MetricsSnapshot
    target_name: str
    run_id: str
    output_dir: Path

    # Result containers
    results_rows: list[dict[str, Any]] = field(default_factory=list)
    skipped_rows: list[dict[str, Any]] = field(default_factory=list)
    index_rows: list[dict[str, Any]] = field(default_factory=list)
    summary_entries: list[dict[str, Any]] = field(default_factory=list)
    metrics_entries: list[dict[str, Any]] = field(default_factory=list)
    script_entries: list[dict[str, Any]] = field(default_factory=list)
    overloaded_configs: list[list[tuple[str, int]]] = field(default_factory=list)


class DfaasRunPlanner:
    """Build the execution plan and initialize run-scoped services."""

    def __init__(
        self,
        *,
        config: DfaasConfig,
        exec_ctx: ExecutionContext,
        planner: DfaasPlanBuilder,
        metrics_collector: MetricsCollector,
        log_manager: DfaasLogManager,
        annotations: DfaasAnnotationService,
        replicas_provider: Callable[[list[str]], dict[str, int]],
    ) -> None:
        self._config = config
        self._exec_ctx = exec_ctx
        self._planner = planner
        self._metrics_collector = metrics_collector
        self._log_manager = log_manager
        self._annotations = annotations
        self._replicas_provider = replicas_provider

    def prepare(self) -> DfaasRunContext:
        output_dir = self._resolve_output_dir()
        function_names = self._planner.build_function_names()
        rates = self._planner.build_rates()
        rates_by_function = self._planner.build_rates_by_function(rates)
        configs = self._planner.build_configurations(
            function_names,
            rates,
            rates_by_function=rates_by_function,
        )

        existing_index = self._load_index(output_dir)
        base_idle = self._metrics_collector.get_node_snapshot()

        cooldown_manager = CooldownManager(
            max_wait_seconds=self._config.cooldown.max_wait_seconds,
            sleep_step_seconds=self._config.cooldown.sleep_step_seconds,
            idle_threshold_pct=self._config.cooldown.idle_threshold_pct,
            metrics_provider=self._metrics_collector.get_node_snapshot,
            replicas_provider=self._replicas_provider,
        )

        target_name = self._exec_ctx.host
        run_id = self._resolve_run_id()
        self._log_manager.attach_handlers(output_dir, run_id)
        self._annotations.setup()

        return DfaasRunContext(
            function_names=function_names,
            configs=configs,
            existing_index=existing_index,
            cooldown_manager=cooldown_manager,
            base_idle=base_idle,
            target_name=target_name,
            run_id=run_id,
            output_dir=output_dir,
        )

    def _resolve_output_dir(self) -> Path:
        if self._config.output_dir:
            return Path(self._config.output_dir).expanduser()
        output_dir = self._load_output_dir_from_generated()
        if output_dir:
            return output_dir
        return Path.cwd() / "benchmark_results" / "peva_faas"

    def _load_output_dir_from_generated(self) -> Path | None:
        cfg_path = Path("benchmark_config.generated.json")
        if not cfg_path.exists():
            return None
        try:
            data = json.loads(cfg_path.read_text())
            output_root = Path(data.get("output_dir", "."))
            workloads = data.get("workloads", {})
            workload_name = self._find_workload_name(workloads)
            return output_root / workload_name
        except (json.JSONDecodeError, OSError, TypeError, KeyError) as exc:
            logger.debug("Could not parse config file %s: %s", cfg_path, exc)
            return None

    @staticmethod
    def _find_workload_name(workloads: dict[str, Any]) -> str:
        for name, entry in workloads.items():
            if isinstance(entry, dict) and entry.get("plugin") == "peva_faas":
                return name
        return "peva_faas"

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
        except (OSError, csv.Error) as exc:
            logger.warning("Could not read index file %s: %s", index_path, exc)
            return set()
        except (SyntaxError, ValueError) as exc:
            logger.warning("Invalid data in index file %s: %s", index_path, exc)
            return set()

    def _resolve_run_id(self) -> str:
        if self._config.run_id:
            return self._config.run_id
        cfg_path = Path("benchmark_config.generated.json")
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text())
                output_dir = Path(data.get("output_dir", "."))
                return output_dir.parent.name
            except (json.JSONDecodeError, OSError, TypeError) as exc:
                logger.debug("Could not parse config for run_id: %s", exc)
        return f"run-{int(time.time())}"


class DfaasConfigExecutor:
    """Execute planned DFaaS configurations."""

    def __init__(
        self,
        *,
        config: DfaasConfig,
        k6_runner: K6Runner,
        metrics_collector: MetricsCollector,
        result_builder: DfaasResultBuilder,
        annotations: DfaasAnnotationService,
        log_manager: DfaasLogManager,
        duration_seconds: int,
        outputs_provider: Callable[[], list[str]],
        tags_provider: Callable[[str], dict[str, str]],
        replicas_provider: Callable[[list[str]], dict[str, int]],
    ) -> None:
        self._config = config
        self._k6_runner = k6_runner
        self._metrics_collector = metrics_collector
        self._result_builder = result_builder
        self._annotations = annotations
        self._log_manager = log_manager
        self._duration_seconds = duration_seconds
        self._outputs_provider = outputs_provider
        self._tags_provider = tags_provider
        self._replicas_provider = replicas_provider

    def execute(self, ctx: DfaasRunContext) -> None:
        total_configs = max(1, len(ctx.configs))
        total_iterations = max(1, self._config.iterations)

        for idx, config_pairs in enumerate(ctx.configs, start=1):
            self._execute_single_config(
                ctx, config_pairs, idx, total_configs, total_iterations
            )

    def _execute_single_config(
        self,
        ctx: DfaasRunContext,
        config_pairs: list[tuple[str, int]],
        idx: int,
        total_configs: int,
        total_iterations: int,
    ) -> None:
        key = config_key(config_pairs)
        cfg_id = config_id(config_pairs)
        pairs_label = self._format_pairs_label(config_pairs)

        skip_reason = self._check_skip_reason(ctx, config_pairs, key)
        if skip_reason:
            self._log_skipped_config(
                ctx,
                config_pairs,
                cfg_id,
                pairs_label,
                skip_reason,
                idx,
                total_configs,
                total_iterations,
            )
            return

        self._annotations.annotate_config_change(ctx.run_id, cfg_id, pairs_label)

        script, metric_ids = self._k6_runner.build_script(
            config_pairs, self._config.functions
        )
        ctx.script_entries.append({"config_id": cfg_id, "script": script})

        overload_counter = self._run_config_iterations(
            ctx,
            config_pairs,
            script,
            metric_ids,
            cfg_id,
            pairs_label,
            idx,
            total_configs,
            total_iterations,
        )
        if overload_counter is None:
            return

        if overload_counter > self._config.iterations / 2:
            ctx.overloaded_configs.append(list(config_pairs))

        self._append_index_row(ctx, key)

    @staticmethod
    def _check_skip_reason(
        ctx: DfaasRunContext,
        config_pairs: list[tuple[str, int]],
        key: tuple[tuple[str, ...], tuple[int, ...]],
    ) -> str | None:
        if any(dominates(over, config_pairs) for over in ctx.overloaded_configs):
            return "dominated_by_overload"
        if key in ctx.existing_index:
            return "already_indexed"
        return None

    def _log_skipped_config(
        self,
        ctx: DfaasRunContext,
        config_pairs: list[tuple[str, int]],
        cfg_id: str,
        pairs_label: str,
        skip_reason: str,
        idx: int,
        total_configs: int,
        total_iterations: int,
    ) -> None:
        for iteration in range(1, total_iterations + 1):
            message = (
                "DFaaS config "
                f"{idx}/{total_configs} iter {iteration}/{total_iterations} "
                f"({cfg_id}) skipped={skip_reason}: {pairs_label}"
            )
            logger.info("%s", message)
            self._log_manager.emit_log(message)
        ctx.skipped_rows.append(
            self._result_builder.build_skipped_row(ctx.function_names, config_pairs)
        )

    def _execute_iteration(
        self,
        ctx: DfaasRunContext,
        config_pairs: list[tuple[str, int]],
        script: str,
        metric_ids: dict[str, str],
        cfg_id: str,
        pairs_label: str,
        idx: int,
        total_configs: int,
        iteration: int,
        total_iterations: int,
    ) -> bool:
        message = self._build_iteration_message(
            cfg_id, pairs_label, idx, total_configs, iteration, total_iterations
        )
        self._emit_iteration_message(message)

        idle_snapshot, rest_seconds = self._perform_cooldown(ctx, cfg_id)
        k6_result, start_time, end_time = self._run_k6_iteration(
            ctx, cfg_id, script, metric_ids
        )

        summary_data = k6_result.summary
        summary_metrics = self._parse_summary_or_raise(summary_data, metric_ids, cfg_id)
        replicas = self._replicas_provider(getattr(ctx, "function_names", []))
        config_fn_names = [name for name, _ in config_pairs]
        metrics = self._collect_metrics(config_fn_names, start_time, end_time)

        row, overloaded = self._result_builder.build_result_row(
            getattr(ctx, "function_names", []),
            config_pairs,
            summary_metrics,
            replicas,
            metrics,
            idle_snapshot,
            rest_seconds,
        )

        if overloaded:
            self._annotations.annotate_overload(
                ctx.run_id, cfg_id, pairs_label, iteration
            )

        self._append_iteration_entries(
            ctx, cfg_id, iteration, summary_data, metrics, row
        )
        return overloaded

    @staticmethod
    def _build_iteration_message(
        cfg_id: str,
        pairs_label: str,
        idx: int,
        total_configs: int,
        iteration: int,
        total_iterations: int,
    ) -> str:
        return (
            "DFaaS config "
            f"{idx}/{total_configs} iter {iteration}/{total_iterations} "
            f"({cfg_id}): {pairs_label}"
        )

    def _emit_iteration_message(self, message: str) -> None:
        logger.info("%s", message)
        self._log_manager.emit_log(message)

    def _perform_cooldown(
        self, ctx: DfaasRunContext, cfg_id: str
    ) -> tuple[MetricsSnapshot, int]:
        logger.info("DFaaS cooldown start (%s)", cfg_id)
        cooldown_result = ctx.cooldown_manager.wait_for_idle(
            ctx.base_idle, getattr(ctx, "function_names", [])
        )
        idle_snapshot = cooldown_result.snapshot
        rest_seconds = cooldown_result.waited_seconds
        logger.info("DFaaS cooldown complete (%s) waited=%ds", cfg_id, rest_seconds)
        return idle_snapshot, rest_seconds

    def _run_k6_iteration(
        self,
        ctx: DfaasRunContext,
        cfg_id: str,
        script: str,
        metric_ids: dict[str, str],
    ) -> tuple[Any, float, float]:
        start_time = time.time()
        logger.info("DFaaS k6 execute start (%s)", cfg_id)
        k6_result = self._k6_runner.execute(
            cfg_id,
            script,
            ctx.target_name,
            ctx.run_id,
            metric_ids,
            output_dir=ctx.output_dir,
            outputs=self._outputs_provider(),
            tags=self._tags_provider(ctx.run_id),
        )
        logger.info(
            "DFaaS k6 execute done (%s) duration=%.1fs",
            cfg_id,
            k6_result.duration_seconds,
        )
        end_time = time.time()
        return k6_result, start_time, end_time

    def _parse_summary_or_raise(
        self,
        summary_data: dict[str, Any],
        metric_ids: dict[str, str],
        cfg_id: str,
    ) -> dict[str, dict[str, float]]:
        try:
            return self._k6_runner.parse_summary(summary_data, metric_ids)
        except ValueError as exc:
            self._log_summary_parse_failure(summary_data, metric_ids)
            raise K6ExecutionError(
                cfg_id,
                f"missing k6 summary metrics: {exc}",
            ) from exc

    @staticmethod
    def _log_summary_parse_failure(
        summary_data: dict[str, Any] | None,
        metric_ids: dict[str, str],
    ) -> None:
        metrics_dict = summary_data.get("metrics", {}) if summary_data else {}
        sample_metric = None
        for mid in metric_ids.values():
            key = f"success_rate_{mid}"
            if key in metrics_dict:
                sample_metric = {key: metrics_dict[key]}
                break
        logger.error(
            "Summary parsing failed. metric_ids=%s, summary_keys=%s, sample_metric=%s",
            metric_ids,
            list(metrics_dict.keys()),
            sample_metric,
        )

    def _collect_metrics(
        self, config_fn_names: list[str], start_time: float, end_time: float
    ) -> dict[str, Any]:
        return self._metrics_collector.collect_all_metrics(
            config_fn_names,
            start_time,
            end_time,
            self._duration_seconds,
        )

    @staticmethod
    def _append_iteration_entries(
        ctx: DfaasRunContext,
        cfg_id: str,
        iteration: int,
        summary_data: dict[str, Any],
        metrics: dict[str, Any],
        row: dict[str, Any],
    ) -> None:
        ctx.results_rows.append(row)
        ctx.metrics_entries.append(
            {
                "config_id": cfg_id,
                "iteration": iteration,
                "metrics": metrics,
            }
        )
        ctx.summary_entries.append(
            {
                "config_id": cfg_id,
                "iteration": iteration,
                "summary": summary_data,
            }
        )

    def _run_config_iterations(
        self,
        ctx: DfaasRunContext,
        config_pairs: list[tuple[str, int]],
        script: str,
        metric_ids: dict[str, str],
        cfg_id: str,
        pairs_label: str,
        idx: int,
        total_configs: int,
        total_iterations: int,
    ) -> int | None:
        overload_counter = 0
        try:
            for iteration in range(1, total_iterations + 1):
                overloaded = self._execute_iteration(
                    ctx,
                    config_pairs,
                    script,
                    metric_ids,
                    cfg_id,
                    pairs_label,
                    idx,
                    total_configs,
                    iteration,
                    total_iterations,
                )
                if overloaded:
                    overload_counter += 1
        except CooldownTimeoutError as exc:
            self._handle_cooldown_timeout(ctx, config_pairs, cfg_id, exc)
            return None
        except K6ExecutionError as exc:
            self._handle_k6_error(ctx, config_pairs, cfg_id, exc)
            return None
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            self._handle_execution_error(ctx, config_pairs, cfg_id, exc)
            return None
        return overload_counter

    @staticmethod
    def _format_pairs_label(config_pairs: list[tuple[str, int]]) -> str:
        return ", ".join(
            f"{name}={rate}"
            for name, rate in sorted(config_pairs, key=lambda pair: pair[0])
        )

    def _append_index_row(
        self,
        ctx: DfaasRunContext,
        key: tuple[tuple[str, ...], tuple[int, ...]],
    ) -> None:
        ctx.index_rows.append(
            {
                "functions": list(key[0]),
                "rates": list(key[1]),
                "results_file": "results.csv",
            }
        )

    def _append_skipped_row(
        self, ctx: DfaasRunContext, config_pairs: list[tuple[str, int]]
    ) -> None:
        ctx.skipped_rows.append(
            self._result_builder.build_skipped_row(ctx.function_names, config_pairs)
        )

    def _handle_cooldown_timeout(
        self,
        ctx: DfaasRunContext,
        config_pairs: list[tuple[str, int]],
        cfg_id: str,
        exc: CooldownTimeoutError,
    ) -> None:
        logger.warning(
            "Config %s skipped: cooldown timeout after %ds (max: %ds)",
            cfg_id,
            exc.waited_seconds,
            exc.max_seconds,
        )
        message = (
            f"Cooldown timeout after {exc.waited_seconds}s (max {exc.max_seconds}s)"
        )
        self._annotations.annotate_error(ctx.run_id, cfg_id, message)
        self._append_skipped_row(ctx, config_pairs)

    def _handle_k6_error(
        self,
        ctx: DfaasRunContext,
        config_pairs: list[tuple[str, int]],
        cfg_id: str,
        exc: K6ExecutionError,
    ) -> None:
        logger.error("Config %s failed: k6 execution error: %s", cfg_id, exc)
        if exc.stderr:
            logger.debug("k6 stderr: %s", exc.stderr)
        self._annotations.annotate_error(
            ctx.run_id,
            cfg_id,
            f"k6 execution error: {exc}",
        )
        self._append_skipped_row(ctx, config_pairs)

    def _handle_execution_error(
        self,
        ctx: DfaasRunContext,
        config_pairs: list[tuple[str, int]],
        cfg_id: str,
        exc: Exception,
    ) -> None:
        logger.error("Config %s failed: %s: %s", cfg_id, type(exc).__name__, exc)
        self._annotations.annotate_error(
            ctx.run_id,
            cfg_id,
            f"{type(exc).__name__}: {exc}",
        )
        self._append_skipped_row(ctx, config_pairs)


class DfaasResultWriter:
    """Build final DFaaS result payloads."""

    def __init__(self, config: DfaasConfig) -> None:
        self._config = config

    def build(self, ctx: DfaasRunContext) -> dict[str, Any]:
        function_names = getattr(ctx, "function_names", None)
        if not function_names:
            function_names = sorted(fn.name for fn in self._config.functions)

        return {
            "returncode": 0,
            "success": True,
            "peva_faas_functions": function_names,
            "peva_faas_results": ctx.results_rows,
            "peva_faas_skipped": ctx.skipped_rows,
            "peva_faas_index": ctx.index_rows,
            "peva_faas_summaries": ctx.summary_entries,
            "peva_faas_metrics": ctx.metrics_entries,
            "peva_faas_scripts": ctx.script_entries,
        }
