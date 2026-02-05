"""Grafana datasource/dashboard assets for the PEVA-faas plugin."""

from __future__ import annotations

from pathlib import Path

from lb_plugins.observability import (
    GrafanaAssets,
    GrafanaDashboardAsset,
    GrafanaDatasourceAsset,
)

GRAFANA_DASHBOARD_PATH = Path(__file__).parent / "grafana" / "peva_faas-dashboard.json"
GRAFANA_K6_DASHBOARD_PATH = (
    Path(__file__).parent / "grafana" / "peva_faas-k6-dashboard.json"
)
GRAFANA_DASHBOARD_UID = "peva_faas-overview"
GRAFANA_K6_DASHBOARD_UID = "peva_faas-k6-overview"
GRAFANA_PROMETHEUS_DATASOURCE_NAME = "peva_faas-prometheus"

GRAFANA_ASSETS = GrafanaAssets(
    datasources=(
        GrafanaDatasourceAsset(
            name=GRAFANA_PROMETHEUS_DATASOURCE_NAME,
            datasource_type="prometheus",
            access="proxy",
            url_from_config="prometheus_url",
            per_host=True,
            name_template="PEVA-faas Prometheus {host.name}",
            url_template="{config.prometheus_url}",
        ),
    ),
    dashboards=(
        GrafanaDashboardAsset(
            name="peva_faas",
            path=GRAFANA_DASHBOARD_PATH,
        ),
        GrafanaDashboardAsset(
            name="peva_faas-k6",
            path=GRAFANA_K6_DASHBOARD_PATH,
        ),
    ),
)
