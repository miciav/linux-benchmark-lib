from __future__ import annotations

import ast
import csv
import json
import logging
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from .config import DfaasConfig
from .context import ExecutionContext
from .exceptions import K6ExecutionError
from .services import (
    CooldownManager,
    CooldownTimeoutError,
    DfaasResultBuilder,
    DfaasAnnotationService,
    DfaasLogManager,
    DfaasPlanBuilder,
    MetricsCollector,
    MetricsSnapshot,
)
from .services.k6_runner import K6Runner
from .services.plan_builder import config_id, config_key, dominates, parse_duration_seconds
from ...base_generator import BaseGenerator

logger = logging.getLogger(__name__)


@dataclass
class _RunContext:
    """Context object holding state for a benchmark run."""

    function_names: list[str]
    configs: list[list[tuple[str, int]]]
    existing_index: set[tuple[tuple[str, ...], tuple[int, ...]]]
    cooldown_manager: CooldownManager
    base_idle: MetricsSnapshot
    target_name: str
    run_id: str

    # Result containers
    results_rows: list[dict[str, Any]] = field(default_factory=list)
    skipped_rows: list[dict[str, Any]] = field(default_factory=list)
    index_rows: list[dict[str, Any]] = field(default_factory=list)
    summary_entries: list[dict[str, Any]] = field(default_factory=list)
    metrics_entries: list[dict[str, Any]] = field(default_factory=list)
    script_entries: list[dict[str, Any]] = field(default_factory=list)
    overloaded_configs: list[list[tuple[str, int]]] = field(default_factory=list)

class DfaasGenerator(BaseGenerator):
    """DFaaS generator that orchestrates one config at a time."""

    def __init__(
        self,
        config: DfaasConfig,
        name: str = "DfaasGenerator",
        execution_context: ExecutionContext | None = None,
    ):
        super().__init__(name)
        self.config = config
        self._exec_ctx = execution_context or ExecutionContext.from_environment()
        self._planner = DfaasPlanBuilder(config)
        self.expected_runtime_seconds = self._estimate_runtime()
        self._log_manager = DfaasLogManager(
            config=config,
            exec_ctx=self._exec_ctx,
            logger=logger,
        )
        self._annotations = DfaasAnnotationService(config.grafana, self._exec_ctx)
        self._k6_runner = K6Runner(
            k6_host=config.k6_host,
            k6_user=config.k6_user,
            k6_ssh_key=config.k6_ssh_key,
            k6_port=config.k6_port,
            k6_workspace_root=config.k6_workspace_root,
            gateway_url=self._resolve_url_template(config.gateway_url, self._exec_ctx.host),
            duration=config.duration,
            log_stream_enabled=config.k6_log_stream,
            log_callback=self._log_manager.emit_k6_log,
            log_to_logger=True,
        )
        self._metrics_collector = MetricsCollector(
            prometheus_url=self._resolve_url_template(config.prometheus_url, self._exec_ctx.host),
            queries_path=config.queries_path,
            duration=config.duration,
            scaphandre_enabled=config.scaphandre_enabled,
            function_pid_regexes=config.function_pid_regexes,
        )
        self._result_builder = DfaasResultBuilder(config.overload)
        self._duration_seconds = parse_duration_seconds(config.duration)

    def _estimate_runtime(self) -> int:
        return self._planner.estimate_runtime_seconds()

    def _validate_environment(self) -> bool:
        required = ["faas-cli"]
        for tool in required:
            if subprocess.run(["which", tool], capture_output=True).returncode != 0:
                logger.error("Required tool missing: %s", tool)
                return False
        # Resolve k6_ssh_key: try configured path first, then fallback to standard remote path
        if not self._resolve_k6_ssh_key():
            return False
        return True

    def _resolve_k6_ssh_key(self) -> bool:
        """Resolve k6_ssh_key path, trying fallback locations for remote execution."""
        if not self.config.k6_ssh_key:
            return True
        configured_path = Path(self.config.k6_ssh_key).expanduser()
        if configured_path.exists():
            return True
        # Fallback: check standard path where setup_global.yml copies the key
        fallback_path = Path.home() / ".ssh" / "dfaas_k6_key"
        if fallback_path.exists():
            logger.info(
                "k6_ssh_key not found at %s, using fallback: %s",
                self.config.k6_ssh_key,
                fallback_path,
            )
            resolved_path = str(fallback_path)
            # Update config with resolved path
            object.__setattr__(self.config, "k6_ssh_key", resolved_path)
            # Also update K6Runner which was created with the original path
            self._k6_runner.k6_ssh_key = resolved_path
            return True
        logger.error(
            "k6_ssh_key does not exist at configured path (%s) or fallback (%s)",
            self.config.k6_ssh_key,
            fallback_path,
        )
        return False

    def _stop_workload(self) -> None:
        return None

    def _run_command(self) -> None:
        """Execute DFaaS benchmark run."""
        ctx = self._prepare_run()
        self._annotations.annotate_run_start(ctx.run_id)
        try:
            self._execute_configs(ctx)
        finally:
            self._annotations.annotate_run_end(ctx.run_id)
        self._finalize_results(ctx)

    def _prepare_run(self) -> _RunContext:
        """Prepare context for benchmark run.

        Returns:
            _RunContext with configurations and initialized services
        """
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
            max_wait_seconds=self.config.cooldown.max_wait_seconds,
            sleep_step_seconds=self.config.cooldown.sleep_step_seconds,
            idle_threshold_pct=self.config.cooldown.idle_threshold_pct,
            metrics_provider=self._metrics_collector.get_node_snapshot,
            replicas_provider=self._get_function_replicas,
        )

        target_name = self._exec_ctx.host
        run_id = self._resolve_run_id()
        self._log_manager.attach_handlers(output_dir, run_id)
        self._annotations.setup()

        return _RunContext(
            function_names=function_names,
            configs=configs,
            existing_index=existing_index,
            cooldown_manager=cooldown_manager,
            base_idle=base_idle,
            target_name=target_name,
            run_id=run_id,
        )

    def _get_local_ip(self) -> str:
        """Resolve the primary local IP address."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't even have to be reachable
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    def _resolve_url_template(self, url: str, target_name: str) -> str:
        """Resolve {host.address} in URL with best available address."""
        if "{host.address}" in url:
            replacement = (
                self._exec_ctx.host_address
                or target_name
                or self._get_local_ip()
            )
            url = url.replace("{host.address}", replacement)
        
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url
        
        # Fallback for localhost replacement logic
        host = parsed.hostname
        if host in {"127.0.0.1", "localhost", "0.0.0.0"} and target_name:
            port = parsed.port
            netloc = f"{target_name}:{port}" if port else target_name
            return urlunparse(parsed._replace(netloc=netloc))
        return url

    def _resolve_prometheus_url(self, target_name: str) -> str:
        return self._resolve_url_template(self.config.prometheus_url, target_name)

    def _build_k6_tags(self, run_id: str) -> dict[str, str]:
        tags = {key: str(value) for key, value in self.config.k6_tags.items()}
        tags["run_id"] = run_id
        tags["component"] = "k6"
        tags["workload"] = "dfaas"
        tags["repetition"] = str(self._exec_ctx.repetition)
        return tags

    def _resolve_k6_outputs(self) -> list[str]:
        """Resolve k6 output configurations.

        Note: Standard k6 does not support Loki output - it requires a custom
        build with xk6-loki extension. DFaaS logs are sent to Loki via Python
        logging handlers instead. Users can configure custom outputs via k6_outputs.
        """
        outputs: list[str] = []
        for output in self.config.k6_outputs:
            if output is None:
                continue
            cleaned = str(output).strip()
            if cleaned:
                outputs.append(cleaned)
        return outputs

    def _execute_configs(self, ctx: _RunContext) -> None:
        """Execute all configurations.

        Args:
            ctx: Run context with configurations and services
        """
        total_configs = max(1, len(ctx.configs))
        total_iterations = max(1, self.config.iterations)

        for idx, config_pairs in enumerate(ctx.configs, start=1):
            self._execute_single_config(ctx, config_pairs, idx, total_configs, total_iterations)

    def _execute_single_config(
        self,
        ctx: _RunContext,
        config_pairs: list[tuple[str, int]],
        idx: int,
        total_configs: int,
        total_iterations: int,
    ) -> None:
        """Execute a single configuration with all iterations.

        Args:
            ctx: Run context
            config_pairs: Configuration pairs (function_name, rate)
            idx: Configuration index (1-based)
            total_configs: Total number of configurations
            total_iterations: Total iterations per configuration
        """
        key = config_key(config_pairs)
        cfg_id = config_id(config_pairs)
        pairs_label = ", ".join(
            f"{name}={rate}"
            for name, rate in sorted(config_pairs, key=lambda pair: pair[0])
        )

        # Check skip conditions
        skip_reason = self._check_skip_reason(ctx, config_pairs, key)
        if skip_reason:
            self._log_skipped_config(
                ctx, config_pairs, cfg_id, pairs_label, skip_reason,
                idx, total_configs, total_iterations
            )
            return

        self._annotations.annotate_config_change(ctx.run_id, cfg_id, pairs_label)

        # Build k6 script
        script, metric_ids = self._k6_runner.build_script(
            config_pairs, self.config.functions
        )
        ctx.script_entries.append({"config_id": cfg_id, "script": script})

        # Execute iterations
        overload_counter = 0
        try:
            for iteration in range(1, total_iterations + 1):
                overloaded = self._execute_iteration(
                    ctx, config_pairs, script, metric_ids, cfg_id, pairs_label,
                    idx, total_configs, iteration, total_iterations
                )
                if overloaded:
                    overload_counter += 1

            # Track overloaded configs
            if overload_counter > self.config.iterations / 2:
                ctx.overloaded_configs.append(list(config_pairs))

            # Add to index
            ctx.index_rows.append({
                "functions": list(key[0]),
                "rates": list(key[1]),
                "results_file": "results.csv",
            })
        except CooldownTimeoutError as exc:
            logger.warning(
                "Config %s skipped: cooldown timeout after %ds (max: %ds)",
                cfg_id, exc.waited_seconds, exc.max_seconds
            )
            self._annotations.annotate_error(
                ctx.run_id,
                cfg_id,
                f"Cooldown timeout after {exc.waited_seconds}s (max {exc.max_seconds}s)",
            )
            ctx.skipped_rows.append(
                self._result_builder.build_skipped_row(
                    ctx.function_names, config_pairs
                )
            )
        except K6ExecutionError as exc:
            logger.error("Config %s failed: k6 execution error: %s", cfg_id, exc)
            if exc.stderr:
                logger.debug("k6 stderr: %s", exc.stderr)
            self._annotations.annotate_error(
                ctx.run_id,
                cfg_id,
                f"k6 execution error: {exc}",
            )
            ctx.skipped_rows.append(
                self._result_builder.build_skipped_row(
                    ctx.function_names, config_pairs
                )
            )
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            logger.error("Config %s failed: %s: %s", cfg_id, type(exc).__name__, exc)
            self._annotations.annotate_error(
                ctx.run_id,
                cfg_id,
                f"{type(exc).__name__}: {exc}",
            )
            ctx.skipped_rows.append(
                self._result_builder.build_skipped_row(
                    ctx.function_names, config_pairs
                )
            )

    def _check_skip_reason(
        self,
        ctx: _RunContext,
        config_pairs: list[tuple[str, int]],
        key: tuple[tuple[str, ...], tuple[int, ...]],
    ) -> str | None:
        """Check if configuration should be skipped.

        Returns:
            Skip reason string or None if config should run
        """
        if any(dominates(over, config_pairs) for over in ctx.overloaded_configs):
            return "dominated_by_overload"
        if key in ctx.existing_index:
            return "already_indexed"
        return None

    def _log_skipped_config(
        self,
        ctx: _RunContext,
        config_pairs: list[tuple[str, int]],
        cfg_id: str,
        pairs_label: str,
        skip_reason: str,
        idx: int,
        total_configs: int,
        total_iterations: int,
    ) -> None:
        """Log and record skipped configuration."""
        for iteration in range(1, total_iterations + 1):
            message = (
                "DFaaS config "
                f"{idx}/{total_configs} iter {iteration}/{total_iterations} "
                f"({cfg_id}) skipped={skip_reason}: {pairs_label}"
            )
            logger.info("%s", message)
            self._log_manager.emit_log(message)
        ctx.skipped_rows.append(
            self._result_builder.build_skipped_row(
                ctx.function_names, config_pairs
            )
        )

    def _execute_iteration(
        self,
        ctx: _RunContext,
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
        """Execute a single iteration of a configuration.

        Returns:
            True if system was overloaded during this iteration
        """
        message = (
            "DFaaS config "
            f"{idx}/{total_configs} iter {iteration}/{total_iterations} "
            f"({cfg_id}): {pairs_label}"
        )
        logger.info("%s", message)
        self._log_manager.emit_log(message)

        # Wait for cooldown
        logger.info("DFaaS cooldown start (%s)", cfg_id)
        cooldown_result = ctx.cooldown_manager.wait_for_idle(
            ctx.base_idle, getattr(ctx, "function_names", [])
        )
        idle_snapshot = cooldown_result.snapshot
        rest_seconds = cooldown_result.waited_seconds
        logger.info("DFaaS cooldown complete (%s) waited=%ds", cfg_id, rest_seconds)

        # Execute k6 test
        start_time = time.time()
        logger.info("DFaaS k6 execute start (%s)", cfg_id)
        k6_result = self._k6_runner.execute(
            cfg_id,
            script,
            ctx.target_name,
            ctx.run_id,
            metric_ids,
            outputs=self._resolve_k6_outputs(),
            tags=self._build_k6_tags(ctx.run_id),
        )
        logger.info(
            "DFaaS k6 execute done (%s) duration=%.1fs",
            cfg_id,
            k6_result.duration_seconds,
        )
        summary_data = k6_result.summary
        end_time = time.time()

        # Collect metrics
        try:
            summary_metrics = self._k6_runner.parse_summary(summary_data, metric_ids)
        except ValueError as exc:
            raise K6ExecutionError(
                cfg_id,
                f"missing k6 summary metrics: {exc}",
            ) from exc
        replicas = self._get_function_replicas(getattr(ctx, "function_names", []))
        config_fn_names = [name for name, _ in config_pairs]
        metrics = self._metrics_collector.collect_all_metrics(
            config_fn_names,
            start_time,
            end_time,
            self._duration_seconds,
        )

        # Build result row
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

        # Store results
        ctx.results_rows.append(row)
        ctx.metrics_entries.append({
            "config_id": cfg_id,
            "iteration": iteration,
            "metrics": metrics,
        })
        ctx.summary_entries.append({
            "config_id": cfg_id,
            "iteration": iteration,
            "summary": summary_data,
        })

        return overloaded

    def _finalize_results(self, ctx: _RunContext) -> None:
        """Build final result dictionary.

        Args:
            ctx: Run context with collected results
        """
        # Use getattr to be robust against potential dataclass issues in remote execution
        function_names = getattr(ctx, "function_names", None)
        if not function_names:
            function_names = sorted(fn.name for fn in self.config.functions)

        self._result = {
            "returncode": 0,
            "success": True,
            "dfaas_functions": function_names,
            "dfaas_results": ctx.results_rows,
            "dfaas_skipped": ctx.skipped_rows,
            "dfaas_index": ctx.index_rows,
            "dfaas_summaries": ctx.summary_entries,
            "dfaas_metrics": ctx.metrics_entries,
            "dfaas_scripts": ctx.script_entries,
        }

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
            except (json.JSONDecodeError, OSError, TypeError, KeyError) as exc:
                logger.debug("Could not parse config file %s: %s", cfg_path, exc)
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
        except (OSError, csv.Error) as exc:
            logger.warning("Could not read index file %s: %s", index_path, exc)
            return set()
        except (SyntaxError, ValueError) as exc:
            logger.warning("Invalid data in index file %s: %s", index_path, exc)
            return set()

    def _get_function_replicas(self, function_names: list[str]) -> dict[str, int]:
        replicas = {name: 0 for name in function_names}
        # Use the resolved gateway URL (same as K6Runner uses)
        resolved_gateway = self._k6_runner.gateway_url
        cmd = [
            "faas-cli",
            "list",
            "--gateway",
            resolved_gateway,
            "--tls-no-verify",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as exc:
            logger.error("faas-cli list failed: %s", exc)
            return replicas

        return self._parse_faas_cli_replicas(result.stdout, function_names)

    def _parse_faas_cli_replicas(
        self, output: str, function_names: list[str]
    ) -> dict[str, int]:
        replicas = {name: 0 for name in function_names}
        lines = [line for line in output.splitlines() if line.strip()]
        if not lines:
            return replicas

        header_tokens = lines[0].split()
        header_upper = [token.upper() for token in header_tokens]
        replica_index = (
            header_upper.index("REPLICAS") if "REPLICAS" in header_upper else None
        )

        data_lines = lines
        if header_tokens and header_upper[0] == "NAME":
            data_lines = lines[1:]
            if replica_index is None:
                replica_index = len(header_tokens) - 1

        for line in data_lines:
            parts = line.split()
            if not parts:
                continue
            idx = replica_index if replica_index is not None else len(parts) - 1
            if idx < 0 or idx >= len(parts):
                continue
            name = parts[0]
            if name in replicas:
                try:
                    replicas[name] = int(parts[idx])
                except ValueError:
                    replicas[name] = 0
        return replicas

    def _resolve_run_id(self) -> str:
        if self.config.run_id:
            return self.config.run_id
        cfg_path = Path("benchmark_config.generated.json")
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text())
                output_dir = Path(data.get("output_dir", "."))
                return output_dir.parent.name
            except (json.JSONDecodeError, OSError, TypeError) as exc:
                logger.debug("Could not parse config for run_id: %s", exc)
        return f"run-{int(time.time())}"
