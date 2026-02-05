from __future__ import annotations

import logging
import socket
import subprocess
from pathlib import Path
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
    MetricsCollector,
)
from .services.k6_runner import K6Runner
from .services.plan_builder import parse_duration_seconds
from ...base_generator import BaseGenerator

logger = logging.getLogger(__name__)


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
            gateway_url=self._resolve_url_template(
                config.gateway_url, self._exec_ctx.host
            ),
            duration=config.duration,
            log_stream_enabled=config.k6_log_stream,
            log_callback=self._log_manager.emit_k6_log,
            log_to_logger=True,
        )
        self._metrics_collector = MetricsCollector(
            prometheus_url=self._resolve_url_template(
                config.prometheus_url, self._exec_ctx.host
            ),
            queries_path=config.queries_path,
            duration=config.duration,
            scaphandre_enabled=config.scaphandre_enabled,
            function_pid_regexes=config.function_pid_regexes,
        )
        self._result_builder = DfaasResultBuilder(config.overload)
        self._duration_seconds = parse_duration_seconds(config.duration)
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
        )
        self._result_writer = DfaasResultWriter(self.config)

    def _estimate_runtime(self) -> int:
        return self._planner.estimate_runtime_seconds()

    def _validate_environment(self) -> bool:
        required = ["faas-cli"]
        for tool in required:
            if subprocess.run(["which", tool], capture_output=True).returncode != 0:
                logger.error("Required tool missing: %s", tool)
                return False
        # Resolve k6_ssh_key; fall back to standard remote path.
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
        if host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            return url
        host_address = self._exec_ctx.host_address
        if not host_address:
            return url
        port = parsed.port
        netloc = f"{host_address}:{port}" if port else host_address
        return urlunparse(parsed._replace(netloc=netloc))

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
