"""K6 runner service for executing k6 load tests."""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from ..exceptions import K6ExecutionError

if TYPE_CHECKING:
    from ..plugin import DfaasFunctionConfig

logger = logging.getLogger(__name__)


@dataclass
class K6RunResult:
    """Result of a k6 run."""

    summary: dict[str, Any]
    script: str
    config_id: str
    duration_seconds: float
    metric_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class _K6LogStream:
    """Internal state for k6 log streaming."""

    config_id: str
    proc: subprocess.Popen[str]
    stop_event: threading.Event
    threads: list[threading.Thread]


def _normalize_metric_id(name: str) -> str:
    """Normalize function name to valid k6 metric identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned:
        cleaned = "fn"
    if cleaned[0].isdigit():
        cleaned = f"fn_{cleaned}"
    return cleaned


class K6Runner:
    """Service for running k6 load tests via Ansible.

    Handles:
    - k6 script generation from configuration
    - Playbook execution on k6 host
    - SSH log streaming
    - Summary parsing
    """

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
    ) -> None:
        """Initialize K6Runner.

        Args:
            k6_host: k6 host address
            k6_user: SSH user for k6 host
            k6_ssh_key: Path to SSH private key
            k6_port: SSH port
            k6_workspace_root: Workspace root directory on k6 host
            gateway_url: OpenFaaS gateway URL
            duration: k6 test duration (e.g., "30s")
            log_stream_enabled: Enable SSH log streaming
            log_callback: Optional callback for log events (message: str) -> None
        """
        self.k6_host = k6_host
        self.k6_user = k6_user
        self.k6_ssh_key = k6_ssh_key
        self.k6_port = k6_port
        self.k6_workspace_root = k6_workspace_root
        self.gateway_url = gateway_url
        self.duration = duration
        self.log_stream_enabled = log_stream_enabled
        self._log_callback = log_callback

    def build_script(
        self,
        config_pairs: list[tuple[str, int]],
        functions: list[DfaasFunctionConfig],
    ) -> tuple[str, dict[str, str]]:
        """Generate k6 script for a configuration.

        Args:
            config_pairs: List of (function_name, rate) tuples
            functions: List of function configurations

        Returns:
            Tuple of (script_content, metric_ids_map)
        """
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

            lines.extend(
                [
                    f"const fn_{metric_id} = {{",
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
                    )
                )

        lines.append("export const options = {")
        lines.append("  scenarios: {")
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

    def execute(
        self,
        config_id: str,
        script: str,
        target_name: str,
        run_id: str,
    ) -> K6RunResult:
        """Execute k6 script via Ansible.

        Args:
            config_id: Configuration identifier
            script: k6 script content
            target_name: Target name for k6 workspace path
            run_id: Run identifier for k6 workspace path

        Returns:
            K6RunResult with summary and metadata

        Raises:
            FileNotFoundError: If playbook is missing
            RuntimeError: If k6 execution fails
        """
        playbook = Path(__file__).parent.parent / "ansible" / "run_k6.yml"
        if not playbook.exists():
            raise FileNotFoundError(f"Missing playbook: {playbook}")

        log_stream = self._start_log_stream(config_id, target_name, run_id)
        start_time = time.time()

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                script_path = temp_path / f"config-{config_id}.js"
                script_path.write_text(script)
                summary_path = temp_path / "summary.json"
                inventory_path = temp_path / "inventory.ini"
                inventory_path.write_text(
                    "\n".join(
                        [
                            "[k6]",
                            (
                                f"k6_host ansible_host={self.k6_host} "
                                f"ansible_user={self.k6_user} "
                                f"ansible_port={self.k6_port} "
                                f"ansible_ssh_private_key_file={Path(self.k6_ssh_key).expanduser()} "
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
                    f"config_id={config_id}",
                    "-e",
                    f"script_src={script_path}",
                    "-e",
                    f"summary_fetch_dest={temp_path}/",
                    "-e",
                    f"k6_workspace_root={self.k6_workspace_root}",
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)
                end_time = time.time()

                if result.returncode != 0:
                    raise K6ExecutionError(
                        config_id=config_id,
                        message="k6 playbook failed",
                        stdout=result.stdout,
                        stderr=result.stderr,
                    )

                summary = json.loads(summary_path.read_text())
                return K6RunResult(
                    summary=summary,
                    script=script,
                    config_id=config_id,
                    duration_seconds=end_time - start_time,
                )
        finally:
            self._stop_log_stream(log_stream)

    def parse_summary(
        self,
        summary: dict[str, Any],
        metric_ids: dict[str, str],
    ) -> dict[str, dict[str, float]]:
        """Parse k6 summary to extract per-function metrics.

        Args:
            summary: Raw k6 summary JSON
            metric_ids: Map of function_name -> metric_id

        Returns:
            Dict of function_name -> {success_rate, avg_latency, request_count}
        """
        metrics = summary.get("metrics", {}) or {}
        parsed: dict[str, dict[str, float]] = {}

        for name, metric_id in metric_ids.items():
            success_metric = metrics.get(f"success_rate_{metric_id}", {}).get(
                "values", {}
            )
            latency_metric = metrics.get(f"latency_{metric_id}", {}).get("values", {})
            count_metric = metrics.get(f"request_count_{metric_id}", {}).get(
                "values", {}
            )

            success_rate = float(success_metric.get("rate", 1.0))
            latency_avg = float(latency_metric.get("avg", 0.0))
            request_count = float(
                count_metric.get("count", count_metric.get("rate", 0.0))
            )

            parsed[name] = {
                "success_rate": success_rate,
                "avg_latency": latency_avg,
                "request_count": request_count,
            }

        return parsed

    def _log(self, message: str) -> None:
        """Log message and call callback if set."""
        logger.info("%s", message)
        if self._log_callback:
            self._log_callback(message)

    def _start_log_stream(
        self, config_id: str, target_name: str, run_id: str
    ) -> _K6LogStream | None:
        """Start SSH log streaming from k6 host."""
        if not self.log_stream_enabled:
            self._log("k6 log stream disabled: log_stream_enabled=false")
            return None

        key_path = Path(self.k6_ssh_key).expanduser()
        log_path = (
            f"{self.k6_workspace_root.rstrip('/')}/"
            f"{target_name}/{run_id}/{config_id}/k6.log"
        )
        wait_cmd = (
            "until test -f {path}; do sleep 1; done; tail -n 0 -F {path}"
        ).format(path=shlex.quote(log_path))
        remote_cmd = f"bash -lc {shlex.quote(wait_cmd)}"

        cmd = [
            "ssh",
            "-i",
            str(key_path),
            "-p",
            str(self.k6_port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{self.k6_user}@{self.k6_host}",
            remote_cmd,
        ]

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        except FileNotFoundError:
            self._log("k6 log stream disabled: ssh not available")
            return None

        stop_event = threading.Event()

        def _reader(stream: Any, label: str) -> None:
            for line in iter(stream.readline, ""):
                if stop_event.is_set():
                    break
                clean = line.rstrip()
                if clean:
                    message = f"k6[{config_id}] {label}: {clean}"
                    self._log(message)

        threads = [
            threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        self._log(f"k6[{config_id}] log stream started")

        return _K6LogStream(
            config_id=config_id,
            proc=proc,
            stop_event=stop_event,
            threads=threads,
        )

    def _stop_log_stream(self, stream: _K6LogStream | None) -> None:
        """Stop SSH log streaming."""
        if not stream:
            return

        stream.stop_event.set()
        if stream.proc.poll() is None:
            stream.proc.terminate()
            try:
                stream.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                stream.proc.kill()

        for thread in stream.threads:
            thread.join(timeout=1)

        self._log(f"k6[{stream.config_id}] log stream stopped")
