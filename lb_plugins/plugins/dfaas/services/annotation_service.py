"""Grafana annotation helpers for DFaaS runs."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from ..config import GrafanaConfig
from ..context import ExecutionContext
from ..grafana_assets import GRAFANA_DASHBOARD_UID
from lb_common.api import GrafanaClient

logger = logging.getLogger(__name__)


@dataclass
class DfaasAnnotationService:
    """Coordinates Grafana annotations for DFaaS runs."""

    grafana_config: GrafanaConfig
    exec_ctx: ExecutionContext
    dashboard_uid: str = GRAFANA_DASHBOARD_UID

    _client: GrafanaClient | None = None
    _dashboard_id: int | None = None

    def setup(self) -> None:
        if not self.grafana_config.enabled:
            self._client = None
            self._dashboard_id = None
            return

        client = GrafanaClient(
            base_url=self.grafana_config.url,
            api_key=self.grafana_config.api_key,
            org_id=self.grafana_config.org_id,
        )
        healthy, _ = client.health_check()
        if not healthy:
            logger.warning(
                "Grafana health check failed at %s; annotations will be disabled.",
                self.grafana_config.url,
            )
            return

        self._client = client
        try:
            resp = client.get_dashboard_by_uid(self.dashboard_uid)
            if resp and "dashboard" in resp:
                self._dashboard_id = resp["dashboard"].get("id")
                logger.info("Resolved Grafana dashboard ID: %s", self._dashboard_id)
            else:
                logger.warning(
                    "Grafana dashboard '%s' not found.", self.dashboard_uid
                )
        except Exception as exc:
            logger.warning("Failed to resolve Grafana dashboard: %s", exc)

    def annotate_run_start(self, run_id: str) -> None:
        tags = self._base_tags(run_id) + ["event:run_start"]
        self._queue_annotation(
            text=f"DFaaS run start ({run_id})",
            tags=tags,
        )

    def annotate_run_end(self, run_id: str) -> None:
        tags = self._base_tags(run_id) + ["event:run_end"]
        self._queue_annotation(
            text=f"DFaaS run end ({run_id})",
            tags=tags,
        )

    def annotate_config_change(
        self, run_id: str, cfg_id: str, pairs_label: str
    ) -> None:
        tags = self._base_tags(run_id) + [f"config_id:{cfg_id}", "event:config"]
        self._queue_annotation(
            text=f"Config {cfg_id}: {pairs_label}",
            tags=tags,
        )

    def annotate_overload(
        self,
        run_id: str,
        cfg_id: str,
        pairs_label: str,
        iteration: int,
    ) -> None:
        tags = self._base_tags(run_id) + [
            f"config_id:{cfg_id}",
            f"iteration:{iteration}",
            "event:overload",
        ]
        self._queue_annotation(
            text=(
                f"Overload detected ({cfg_id}) iter {iteration}: {pairs_label}"
            ),
            tags=tags,
        )

    def annotate_error(self, run_id: str, cfg_id: str, message: str) -> None:
        tags = self._base_tags(run_id) + [f"config_id:{cfg_id}", "event:error"]
        self._queue_annotation(
            text=f"Config {cfg_id} error: {message}",
            tags=tags,
        )

    def _base_tags(self, run_id: str) -> list[str]:
        return [
            f"run_id:{run_id}",
            "workload:dfaas",
            "component:dfaas",
            f"repetition:{self.exec_ctx.repetition}",
            f"host:{self.exec_ctx.host}",
            "phase:run",
        ]

    def _queue_annotation(self, *, text: str, tags: list[str]) -> None:
        client = self._client
        if not client:
            return
        dashboard_id = self._dashboard_id
        time_ms = int(time.time() * 1000)

        def _send() -> None:
            try:
                client.create_annotation(
                    text=text,
                    tags=tags,
                    dashboard_id=dashboard_id,
                    time_ms=time_ms,
                )
            except Exception as exc:
                logger.debug("Grafana annotation failed: %s", exc)

        threading.Thread(target=_send, daemon=True).start()
