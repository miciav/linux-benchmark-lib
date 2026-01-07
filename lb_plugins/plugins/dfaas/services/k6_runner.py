"""
K6 runner service for executing k6 load tests using Fabric/SSH.

"""

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
from typing import Any, Iterable, Mapping, TYPE_CHECKING

from fabric import Connection
from invoke.exceptions import UnexpectedExit

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


def _normalize_metric_id(name: str) -> str:
    """Normalize function name to valid k6 metric identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned:
        cleaned = "fn"
    if cleaned[0].isdigit():
        cleaned = f"fn_{cleaned}"
    return cleaned


class K6Runner:
    """Service for running k6 load tests via direct SSH (Fabric).

    Handles:
    - k6 script generation
    - Direct SSH execution (no Ansible overhead)
    - File transfer (SCP)
    - Real-time log streaming
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
        """Generate k6 script for a configuration. (Unchanged logic)"""
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
                    f