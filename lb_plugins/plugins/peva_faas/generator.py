from __future__ import annotations

import importlib
import logging
from pathlib import Path
import socket
import subprocess
from urllib.parse import urlparse, urlunparse

from .config import DfaasConfig
from .context import ExecutionContext
from .services import (
    DfaasAnnotationService,
    DfaasConfigExecutor,
    DfaasLogManager,
    DfaasPlanBuilder,
    DfaasResultBuilder,
    DfaasResultWriter,
    DfaasRunPlanner,
    DuckDBMemoryStore,
    InProcessMemoryEngine,
    MetricsCollector,
    ParquetCheckpoint,
    TensorCache,
)
from .services.algorithm_loader import load_policy_algorithm
from .services.cartesian_scheduler import CartesianScheduler
from .services.k6_runner import K6Runner
from .services.plan_builder import parse_duration_seconds
from ...base_generator import BaseGenerator

logger = logging.getLogger(__name__)


class DfaasGenerator(BaseGenerator):
    """PEVA-faas generator that orchestrates one config at a time."""

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
        self._policy_algorithm = load_policy_algorithm(config.algorithm_entrypoint)
        self._scheduler = CartesianScheduler()
        self.expected_runtime_seconds = self._estimate_runtime()
        self._log_manager = DfaasLogManager(
            config=config,
            exec_ctx=self._exec_ctx,
            logger=logger,
        )
        self._annotations = DfaasAnnotationService(config.grafana, self._exec_ctx)
        self._k6_runner = K6Runner(
            gateway_url=self._resolve_url_template(config.gateway_url),
            duration=config.duration,
            log_stream_enabled=config.k6_log_stream,
            log_callback=self._log_manager.emit_k6_log,
            log_to_logger=True,
        )
        self._metrics_collector = MetricsCollector(
            prometheus_url=self._resolve_prometheus_url(),
            queries_path=config.queries_path,
            duration=config.duration,
            scaphandre_enabled=config.scaphandre_enabled,
            function_pid_regexes=config.function_pid_regexes,
        )
        self._result_builder = DfaasResultBuilder(config.overload)
        self._duration_seconds = parse_duration_seconds(config.duration)
        memory_db_path = Path(config.memory.db_path).expanduser()
        checkpoint = ParquetCheckpoint(memory_db_path, config.memory.schema_version)
        preload_core_dir = (
            Path(config.memory.preload_core_parquet_dir).expanduser()
            if config.memory.preload_core_parquet_dir
            else None
        )
        export_core_dir = (
            Path(config.memory.export_core_parquet_dir).expanduser()
            if config.memory.export_core_parquet_dir
            else None
        )
        export_debug_dir = (
            Path(config.memory.export_raw_debug_parquet_dir).expanduser()
            if config.memory.export_raw_debug_parquet_dir
            else None
        )
        self._memory_engine = InProcessMemoryEngine(
            mode=config.selection_mode,
            batch_size=config.micro_batch_size,
            batch_window_s=config.micro_batch_window_s,
            store=DuckDBMemoryStore(memory_db_path, config.memory.schema_version),
            cache=TensorCache(),
            policy=self._policy_algorithm,
            checkpoint=checkpoint,
            preload_core_dir=preload_core_dir,
            export_core_dir=export_core_dir,
            export_debug_dir=export_debug_dir,
        )
        self._run_planner = DfaasRunPlanner(
            config=self.config,
            exec_ctx=self._exec_ctx,
            planner=self._planner,
            metrics_collector=self._metrics_collector,
            log_manager=self._log_manager,
            annotations=self._annotations,
            replicas_provider=self._get_function_replicas,
        )
        self._config_executor = DfaasConfigExecutor(
            config=self.config,
            k6_runner=self._k6_runner,
            metrics_collector=self._metrics_collector,
            result_builder=self._result_builder,
            annotations=self._annotations,
            log_manager=self._log_manager,
            duration_seconds=self._duration_seconds,
            outputs_provider=self._resolve_k6_outputs,
            tags_provider=self._build_k6_tags,
            replicas_provider=self._get_function_replicas,
            scheduler=self._scheduler,
            memory_engine=self._memory_engine,
        )
        self._result_writer = DfaasResultWriter(self.config)

    def _estimate_runtime(self) -> int:
        return self._planner.estimate_runtime_seconds()

    def _validate_environment(self) -> bool:
        required = ["faas-cli", "k6"]
        for tool in required:
            if subprocess.run(["which", tool], capture_output=True).returncode != 0:
                logger.error("Required tool missing: %s", tool)
                return False
        for module in ("duckdb", "pyarrow"):
            try:
                importlib.import_module(module)
            except ModuleNotFoundError:
                logger.error("Required Python package missing: %s", module)
                return False
        return True

    def _stop_workload(self) -> None:
        return None

    def _run_command(self) -> None:
        """Execute PEVA-faas benchmark run."""
        ctx = self._run_planner.prepare()
        self._annotations.annotate_run_start(ctx.run_id)
        try:
            self._config_executor.execute(ctx)
        finally:
            self._annotations.annotate_run_end(ctx.run_id)
        self._result = self._result_writer.build(ctx)

    def _get_local_ip(self) -> str:
        """Resolve the primary local IP address."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't even have to be reachable
            s.connect(("10.255.255.255", 1))
            ip_address = s.getsockname()[0]
        except Exception:
            ip_address = "127.0.0.1"
        finally:
            s.close()
        return ip_address

    def _resolve_url_template(self, url: str, target_name: str | None = None) -> str:
        """Resolve {host.address} in URL with best available address."""
        url = self._apply_host_placeholder(url, target_name)
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url
        return self._replace_localhost(parsed, url, target_name)

    def _apply_host_placeholder(self, url: str, target_name: str | None) -> str:
        if "{host.address}" not in url:
            return url
        replacement = self._resolve_host_address(target_name)
        return url.replace("{host.address}", replacement)

    def _replace_localhost(self, parsed, url: str, target_name: str | None) -> str:
        # Fallback for localhost replacement logic
        host = parsed.hostname
        if host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            return url
        host_address = self._resolve_host_address(target_name)
        if not host_address:
            return url
        port = parsed.port
        netloc = f"{host_address}:{port}" if port else host_address
        return urlunparse(parsed._replace(netloc=netloc))

    def _resolve_host_address(self, target_name: str | None = None) -> str:
        if self.config.k3s_host:
            return self.config.k3s_host
        if self._exec_ctx.host_address:
            return self._exec_ctx.host_address
        if target_name:
            return target_name
        return self._get_local_ip()

    def _resolve_prometheus_url(self) -> str:
        return self._resolve_url_template(self.config.prometheus_url)

    def _build_k6_tags(self, run_id: str) -> dict[str, str]:
        tags = {key: str(value) for key, value in self.config.k6_tags.items()}
        tags["run_id"] = run_id
        tags["component"] = "k6"
        tags["workload"] = "peva_faas"
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
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
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

        data_lines, replica_index = self._split_faas_cli_lines(lines)
        for line in data_lines:
            self._update_replicas_from_line(line, replica_index, replicas)
        return replicas

    @staticmethod
    def _split_faas_cli_lines(
        lines: list[str],
    ) -> tuple[list[str], int | None]:
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
        return data_lines, replica_index

    @staticmethod
    def _update_replicas_from_line(
        line: str,
        replica_index: int | None,
        replicas: dict[str, int],
    ) -> None:
        parts = line.split()
        if not parts:
            return
        idx = replica_index if replica_index is not None else len(parts) - 1
        if idx < 0 or idx >= len(parts):
            return
        name = parts[0]
        if name not in replicas:
            return
        try:
            replicas[name] = int(parts[idx])
        except ValueError:
            replicas[name] = 0
