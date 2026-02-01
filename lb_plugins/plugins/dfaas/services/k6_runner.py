"K6 runner service for executing k6 load tests using Fabric/SSH."

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, TYPE_CHECKING

from fabric import Connection
from invoke.exceptions import UnexpectedExit

from ..exceptions import K6ExecutionError

if TYPE_CHECKING:
    from ..config import DfaasFunctionConfig

logger = logging.getLogger(__name__)


class _StreamWriter:
    """File-like wrapper that calls a callback for each write."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        self._callback = callback

    def write(self, data: str) -> int:
        if data:
            self._callback(data)
        return len(data)

    def flush(self) -> None:
        pass


@dataclass
class K6RunResult:
    """Result of a k6 run."""

    summary: dict[str, Any]
    script: str
    config_id: str
    duration_seconds: float
    metric_ids: dict[str, str] = field(default_factory=dict)


def _normalize_metric_id(name: str) -> str:
    """Normalize function name to valid k6 metric identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned:
        cleaned = "fn"
    if cleaned[0].isdigit():
        cleaned = f"fn_{cleaned}"
    return cleaned


class K6Runner:
    """Service for running k6 load tests via direct SSH (Fabric)."""

    def __init__(
        self,
        k6_host: str,
        k6_user: str,
        k6_ssh_key: str,
        k6_port: int,
        k6_workspace_root: str,
        gateway_url: str,
        duration: str,
        log_stream_enabled: bool = False,
        log_callback: Any | None = None,
        log_to_logger: bool = True,
    ) -> None:
        self.k6_host = k6_host
        self.k6_user = k6_user
        self.k6_ssh_key = k6_ssh_key
        self.k6_port = k6_port
        self.k6_workspace_root = k6_workspace_root
        self.gateway_url = gateway_url
        self.duration = duration
        self.log_stream_enabled = log_stream_enabled
        self._log_callback = log_callback
        self._log_to_logger = log_to_logger

    def _get_connection(self) -> Connection:
        """Create a Fabric connection to the k6 host."""
        key_path = Path(self.k6_ssh_key).expanduser()
        return Connection(
            host=self.k6_host,
            user=self.k6_user,
            port=self.k6_port,
            connect_kwargs={
                "key_filename": str(key_path),
                "banner_timeout": 30,
            }
        )

    def build_script(
        self,
        config_pairs: list[tuple[str, int]],
        functions: list[DfaasFunctionConfig],
    ) -> tuple[str, dict[str, str]]:
        """Generate k6 script for a configuration."""
        functions_by_name = {fn.name: fn for fn in functions}
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
            url = f"{self.gateway_url.rstrip('/')}/function/{name}"
            exec_name = f"exec_{metric_id}"

            block = [
                f"const fn_{metric_id} = {{",
                f'  method: "{fn_cfg.method}",',
                f'  url: "{url}",',
                f"  body: {body},",
                f"  headers: {headers},",
                f"}};",
                f'const success_rate_{metric_id} = new Rate("success_rate_{metric_id}");',
                f'const latency_{metric_id} = new Trend("latency_{metric_id}");',
                f'const request_count_{metric_id} = new Counter("request_count_{metric_id}");',
                "",
                f"export function {exec_name}() {{ ",
                f"  const res = http.request(fn_{metric_id}.method, fn_{metric_id}.url, fn_{metric_id}.body, {{ headers: fn_{metric_id}.headers }});",
                "  const ok = res.status >= 200 && res.status < 300;",
                f"  success_rate_{metric_id}.add(ok);",
                f"  latency_{metric_id}.add(res.timings.duration);",
                f"  request_count_{metric_id}.add(1);",
                '  check(res, { "status is 2xx": (r) => r.status >= 200 && r.status < 300 });',
                "}",
                "",
            ]
            lines.extend(block)

            if rate > 0:
                vus = max(1, rate)
                scenario_block = [
                    f"    {metric_id}: {{",
                    '      executor: "constant-arrival-rate",',
                    f"      rate: {rate},",
                    '      timeUnit: "1s",',
                    f'      duration: "{self.duration}",',
                    f"      preAllocatedVUs: {vus},",
                    f"      maxVUs: {vus},",
                    f'      exec: "{exec_name}",',
                    f'      tags: {{ function: "{name}" }},',
                    "    },",
                ]
                scenarios.append("\n".join(scenario_block))

        lines.append("export const options = {")
        lines.append("  scenarios: {")
        if scenarios:
            lines.extend(scenarios)
        else:
            lines.append("    idle: {")
            lines.append('      executor: "constant-vus",')
            lines.append("      vus: 1,")
            lines.append(f'      duration: "{self.duration}",')
            lines.append('      exec: "idle_exec",')
            lines.append("    },")
        lines.append("  },")
        lines.append("}")
        lines.append("")

        if not scenarios:
            lines.append("export function idle_exec() {")
            lines.append("  sleep(1);")
            lines.append("}")
            lines.append("")

        return "\n".join(lines), metric_ids

    def execute(
        self,
        config_id: str,
        script: str,
        target_name: str,
        run_id: str,
        metric_ids: dict[str, str],
        *,
        outputs: Iterable[str] | None = None,
        tags: Mapping[str, str] | None = None,
    ) -> K6RunResult:
        """Execute k6 script via Fabric/SSH."""
        conn = self._get_connection()
        start_time = time.time()
        
        workspace = f"{self.k6_workspace_root}/{target_name}/{run_id}/{config_id}"
        script_path = f"{workspace}/script.js"
        summary_path = f"{workspace}/summary.json"
        log_path = f"{workspace}/k6.log"

        try:
            conn.run(f"mkdir -p {workspace}", hide=True, in_stream=False)

            with tempfile.NamedTemporaryFile("w", delete=False) as f:
                f.write(script)
                local_tmp = f.name
            
            try:
                conn.put(local_tmp, script_path)
            finally:
                os.unlink(local_tmp)

            k6_cmd = self._build_k6_command(script_path, summary_path, outputs, tags)
            self._log(f"Running k6 for config {config_id}...")
            
            full_cmd = f"{k6_cmd} 2>&1 | tee {log_path}"
            
            try:
                out_writer = _StreamWriter(self._stream_handler) if self.log_stream_enabled else None
                result = conn.run(
                    full_cmd,
                    hide=True,
                    out_stream=out_writer,
                    warn=True,
                    in_stream=False,  # Disable stdin to avoid pytest capture issues
                )
            except UnexpectedExit as e:
                raise K6ExecutionError(
                    config_id=config_id,
                    message=f"k6 ssh execution failed: {e}",
                    stdout=str(e),
                    stderr="",
                )

            if result.failed:
                raise K6ExecutionError(
                    config_id=config_id,
                    message=f"k6 failed with exit code {result.exited}",
                    stdout=result.stdout,
                    stderr=result.stderr,
                )

            with tempfile.NamedTemporaryFile("w", delete=False) as f:
                local_summary = f.name
            
            try:
                conn.get(summary_path, local_summary)
                summary_data = json.loads(Path(local_summary).read_text())
            finally:
                os.unlink(local_summary)

            end_time = time.time()
            return K6RunResult(
                summary=summary_data,
                script=script,
                config_id=config_id,
                duration_seconds=end_time - start_time,
                metric_ids=metric_ids,
            )

        except Exception as exc:
            if isinstance(exc, K6ExecutionError):
                raise
            raise K6ExecutionError(
                config_id=config_id,
                message=f"SSH execution error: {exc}",
                stdout="",
                stderr=str(exc)
            )
        finally:
            conn.close()

    def _stream_handler(self, data: str) -> None:
        if not self.log_stream_enabled:
            return
        for line in data.splitlines():
            clean = line.strip()
            if clean:
                self._log(f"k6 remote: {clean}")

    def _log(self, message: str) -> None:
        if self._log_callback:
            self._log_callback(message)
        if self._log_to_logger:
            logger.info("%s", message)

    def _build_k6_command(
        self, 
        script_path: str, 
        summary_path: str,
        outputs: Iterable[str] | None,
        tags: Mapping[str, str] | None
    ) -> str:
        parts = ["k6", "run", "--summary-export", summary_path]
        for output in outputs or []:
            if output.strip():
                parts.extend(["--out", output.strip()])
        for k, v in (tags or {}).items():
            parts.extend(["--tag", f"{k}={v}"])
        parts.append(script_path)
        return " ".join(shlex.quote(p) for p in parts)

    def parse_summary(
        self,
        summary: dict[str, Any],
        metric_ids: dict[str, str],
    ) -> dict[str, dict[str, float]]:
        metrics = summary.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError("Missing 'metrics' in k6 summary.")
        parsed: dict[str, dict[str, float]] = {}
        missing: list[str] = []

        for name, metric_id in metric_ids.items():
            success_rate = self._extract_metric_value(
                metrics.get(f"success_rate_{metric_id}"), "rate"
            )
            latency_avg = self._extract_metric_value(
                metrics.get(f"latency_{metric_id}"), "avg"
            )
            request_count = self._extract_metric_value(
                metrics.get(f"request_count_{metric_id}"), "count"
            )
            if request_count is None:
                request_count = self._extract_metric_value(
                    metrics.get(f"request_count_{metric_id}"), "rate"
                )

            if success_rate is None:
                missing.append(f"{name}:success_rate")
            if latency_avg is None:
                missing.append(f"{name}:latency")
            if request_count is None:
                missing.append(f"{name}:request_count")
            if success_rate is None or latency_avg is None or request_count is None:
                continue

            parsed[name] = {
                "success_rate": success_rate,
                "avg_latency": latency_avg,
                "request_count": request_count,
            }

        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing k6 summary metrics: {joined}")

        return parsed

    def _extract_metric_value(
        self, metric: dict[str, Any] | None, key: str
    ) -> float | None:
        """Extract a metric value from k6 summary JSON.

        Supports both old format ({"values": {"rate": ...}}) and
        new format ({"value": ..., "avg": ..., "count": ...}).
        """
        if not isinstance(metric, dict):
            return None

        # Try new k6 format first (values at top level)
        # For Rate metrics: key="rate" maps to "value"
        # For Trend metrics: key="avg" maps to "avg"
        # For Counter metrics: key="count" maps to "count"
        if key == "rate" and "value" in metric:
            return float(metric["value"])
        if key in metric:
            return float(metric[key])

        # Fall back to old format with nested "values" dict
        values = metric.get("values")
        if isinstance(values, dict):
            value = values.get(key)
            if value is not None:
                return float(value)

        return None
