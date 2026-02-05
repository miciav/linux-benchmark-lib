"""K6 runner service for executing k6 load tests locally."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, TYPE_CHECKING

from ..exceptions import K6ExecutionError

if TYPE_CHECKING:
    from ..config import DfaasFunctionConfig

logger = logging.getLogger(__name__)


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
    """Service for running k6 load tests locally."""

    def __init__(
        self,
        gateway_url: str,
        duration: str,
        log_stream_enabled: bool = False,
        log_callback: Any | None = None,
        log_to_logger: bool = True,
    ) -> None:
        self.gateway_url = gateway_url
        self.duration = duration
        self.log_stream_enabled = log_stream_enabled
        self._log_callback = log_callback
        self._log_to_logger = log_to_logger

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
            metric_id = self._unique_metric_id(name, metric_ids)
            metric_ids[name] = metric_id

            exec_name = f"exec_{metric_id}"
            lines.extend(self._build_function_block(fn_cfg, name, metric_id, exec_name))

            scenario = self._build_scenario_block(name, metric_id, exec_name, rate)
            if scenario:
                scenarios.append(scenario)

        lines.extend(self._build_options_block(scenarios))
        if not scenarios:
            lines.extend(self._build_idle_block())

        return "\n".join(lines), metric_ids

    def execute(
        self,
        config_id: str,
        script: str,
        target_name: str,
        run_id: str,
        metric_ids: dict[str, str],
        *,
        output_dir: Path,
        outputs: Iterable[str] | None = None,
        tags: Mapping[str, str] | None = None,
    ) -> K6RunResult:
        """Execute k6 script locally."""
        workspace = output_dir / "k6" / target_name / run_id / config_id
        workspace.mkdir(parents=True, exist_ok=True)
        script_path = workspace / "script.js"
        summary_path = workspace / "summary.json"
        log_path = workspace / "k6.log"

        script_path.write_text(script)
        k6_cmd = self._build_k6_command(script_path, summary_path, outputs, tags)

        start_time = time.time()
        try:
            proc = subprocess.Popen(
                k6_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception as exc:
            raise K6ExecutionError(
                config_id=config_id,
                message=f"local execution failed: {exc}",
                stdout="",
                stderr=str(exc),
            ) from exc

        stdout_chunks: list[str] = []
        with log_path.open("w") as log_handle:
            if proc.stdout:
                for line in proc.stdout:
                    stdout_chunks.append(line)
                    log_handle.write(line)
                    if self.log_stream_enabled:
                        self._stream_handler(line)
            exit_code = proc.wait()

        stdout = "".join(stdout_chunks)
        if exit_code != 0:
            raise K6ExecutionError(
                config_id=config_id,
                message=f"k6 failed with exit code {exit_code}",
                stdout=stdout,
                stderr="",
            )
        if not summary_path.exists():
            raise K6ExecutionError(
                config_id=config_id,
                message="summary file not found",
                stdout=stdout,
                stderr="",
            )

        summary_data = json.loads(summary_path.read_text())
        end_time = time.time()
        return K6RunResult(
            summary=summary_data,
            script=script,
            config_id=config_id,
            duration_seconds=end_time - start_time,
            metric_ids=metric_ids,
        )

    def _stream_handler(self, data: str) -> None:
        if not self.log_stream_enabled:
            return
        for line in data.splitlines():
            clean = line.strip()
            if clean:
                self._log(f"k6: {clean}")

    def _log(self, message: str) -> None:
        if self._log_callback:
            self._log_callback(message)
        if self._log_to_logger:
            logger.info("%s", message)

    def _build_k6_command(
        self,
        script_path: Path | str,
        summary_path: Path | str,
        outputs: Iterable[str] | None,
        tags: Mapping[str, str] | None,
    ) -> list[str]:
        parts = ["k6", "run", "--summary-export", str(summary_path)]
        for output in outputs or []:
            if output.strip():
                parts.extend(["--out", output.strip()])
        for key, value in (tags or {}).items():
            parts.extend(["--tag", f"{key}={value}"])
        parts.append(str(script_path))
        return parts

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
            values, missing_keys = self._parse_metric_values(metrics, metric_id)
            if missing_keys:
                missing.extend(f"{name}:{key}" for key in missing_keys)
                continue
            if values is not None:
                parsed[name] = values

        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing k6 summary metrics: {joined}")

        return parsed

    def _unique_metric_id(self, name: str, metric_ids: dict[str, str]) -> str:
        metric_id = _normalize_metric_id(name)
        if metric_id in metric_ids.values():
            metric_id = f"{metric_id}_{len(metric_ids) + 1}"
        return metric_id

    def _build_function_block(
        self,
        fn_cfg: DfaasFunctionConfig,
        name: str,
        metric_id: str,
        exec_name: str,
    ) -> list[str]:
        body = json.dumps(fn_cfg.body)
        headers = json.dumps(fn_cfg.headers)
        url = f"{self.gateway_url.rstrip('/')}/function/{name}"

        success_metric = f"success_rate_{metric_id}"
        latency_metric = f"latency_{metric_id}"
        request_metric = f"request_count_{metric_id}"

        request_line = (
            f"  const res = http.request("
            f"fn_{metric_id}.method, fn_{metric_id}.url, fn_{metric_id}.body, "
            f"{{ headers: fn_{metric_id}.headers }});"
        )
        check_line = (
            '  check(res, { "status is 2xx": (r) => r.status >= 200 && '
            "r.status < 300 });"
        )

        return [
            f"const fn_{metric_id} = {{",
            f'  method: "{fn_cfg.method}",',
            f'  url: "{url}",',
            f"  body: {body},",
            f"  headers: {headers},",
            "};",
            f'const {success_metric} = new Rate("{success_metric}");',
            f'const {latency_metric} = new Trend("{latency_metric}");',
            f'const {request_metric} = new Counter("{request_metric}");',
            "",
            f"export function {exec_name}() {{",
            request_line,
            "  const ok = res.status >= 200 && res.status < 300;",
            f"  {success_metric}.add(ok);",
            f"  {latency_metric}.add(res.timings.duration);",
            f"  {request_metric}.add(1);",
            check_line,
            "}",
            "",
        ]

    def _build_scenario_block(
        self,
        name: str,
        metric_id: str,
        exec_name: str,
        rate: int,
    ) -> str | None:
        if rate <= 0:
            return None
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
        return "\n".join(scenario_block)

    def _build_options_block(self, scenarios: list[str]) -> list[str]:
        lines = ["export const options = {", "  scenarios: {"]
        if scenarios:
            lines.extend(scenarios)
        else:
            lines.extend(
                [
                    "    idle: {",
                    '      executor: "constant-vus",',
                    "      vus: 1,",
                    f'      duration: "{self.duration}",',
                    '      exec: "idle_exec",',
                    "    },",
                ]
            )
        lines.append("  },")
        lines.append("}")
        lines.append("")
        return lines

    @staticmethod
    def _build_idle_block() -> list[str]:
        return [
            "export function idle_exec() {",
            "  sleep(1);",
            "}",
            "",
        ]

    def _parse_metric_values(
        self, metrics: dict[str, Any], metric_id: str
    ) -> tuple[dict[str, float] | None, list[str]]:
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

        missing: list[str] = []
        if success_rate is None:
            missing.append("success_rate")
        if latency_avg is None:
            missing.append("latency")
        if request_count is None:
            missing.append("request_count")
        if missing:
            return None, missing

        return (
            {
                "success_rate": success_rate,
                "avg_latency": latency_avg,
                "request_count": request_count,
            },
            [],
        )

    def _extract_metric_value(
        self, metric: dict[str, Any] | None, key: str
    ) -> float | None:
        """Extract a metric value from k6 summary JSON.

        Supports both old format ({"values": {"rate": ...}}) and
        new format ({"value": ..., "avg": ..., "count": ...}).
        """
        if not isinstance(metric, dict):
            return None

        if key == "rate" and "value" in metric:
            return float(metric["value"])
        if key in metric:
            return float(metric[key])

        values = metric.get("values")
        if isinstance(values, dict) and key in values:
            return float(values[key])
        return None
