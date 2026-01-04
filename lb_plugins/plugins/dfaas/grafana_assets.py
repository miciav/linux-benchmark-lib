"""Grafana datasource/dashboard assets for the DFaaS plugin."""

from __future__ import annotations

from pathlib import Path

from lb_plugins.observability import (
    GrafanaAssets,
    GrafanaDashboardAsset,
    GrafanaDatasourceAsset,
)

GRAFANA_DASHBOARD_PATH = Path(__file__).parent / "grafana" / "dfaas-dashboard.json"
GRAFANA_PROMETHEUS_DATASOURCE_NAME = "dfaas-prometheus"

GRAFANA_ASSETS = GrafanaAssets(
    datasources=(
        GrafanaDatasourceAsset(
            name=GRAFANA_PROMETHEUS_DATASOURCE_NAME,
            datasource_type="prometheus",
            access="proxy",
            url_from_config="prometheus_url",
        ),
    ),
    dashboards=(
        GrafanaDashboardAsset(
            name="dfaas",
            path=GRAFANA_DASHBOARD_PATH,
        ),
    ),
)

