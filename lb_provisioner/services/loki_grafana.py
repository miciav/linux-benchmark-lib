"""Provision Loki and Grafana together and configure Grafana assets."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib import request, error

from lb_plugins.api import (
    GrafanaAssets,
    GrafanaClient,
)


DEFAULT_LOKI_DATASOURCE_NAME = "loki"
_LOKI_READY_PATH = "/ready"
_LOKI_PUSH_PATH = "/loki/api/v1/push"


@dataclass(frozen=True)
class GrafanaConfigSummary:
    """Summary of Grafana provisioning actions."""

    loki_datasource_id: int | None
    datasources_configured: int
    dashboards_configured: int


@dataclass(frozen=True)
class LokiGrafanaScripts:
    """Script paths for installing/removing Loki and Grafana."""

    loki_install: Path
    loki_uninstall: Path
    grafana_install: Path
    grafana_uninstall: Path


def default_scripts() -> LokiGrafanaScripts:
    """Return script paths relative to the repository root."""
    repo_root = Path(__file__).resolve().parents[2]
    return LokiGrafanaScripts(
        loki_install=repo_root / "scripts" / "install_loki.sh",
        loki_uninstall=repo_root / "scripts" / "uninstall_loki.sh",
        grafana_install=repo_root
        / "lb_plugins"
        / "plugins"
        / "dfaas"
        / "scripts"
        / "install_grafana.sh",
        grafana_uninstall=repo_root
        / "lb_plugins"
        / "plugins"
        / "dfaas"
        / "scripts"
        / "uninstall_grafana.sh",
    )


def normalize_loki_base_url(endpoint: str) -> str:
    """Return the Loki base URL (without the push path)."""
    trimmed = endpoint.rstrip("/")
    if trimmed.endswith(_LOKI_PUSH_PATH):
        trimmed = trimmed[: -len(_LOKI_PUSH_PATH)]
    return trimmed or endpoint


def check_loki_ready(endpoint: str, *, timeout_seconds: float = 2.0) -> bool:
    """Return True if Loki responds to /ready."""
    base = normalize_loki_base_url(endpoint)
    url = f"{base.rstrip('/')}{_LOKI_READY_PATH}"
    try:
        with request.urlopen(url, timeout=timeout_seconds):
            return True
    except (error.URLError, error.HTTPError):
        return False


def check_grafana_ready(
    grafana_url: str,
    *,
    api_key: str | None = None,
    org_id: int = 1,
) -> bool:
    """Return True if Grafana health check succeeds."""
    client = GrafanaClient(base_url=grafana_url, api_key=api_key, org_id=org_id)
    ok, _ = client.health_check()
    return ok


def run_script(script: Path, args: list[str]) -> None:
    """Invoke a provisioning script with arguments."""
    if not script.exists():
        raise FileNotFoundError(f"Script not found: {script}")
    subprocess.run([str(script), *args], check=True)


def install_loki_grafana(
    *,
    mode: str,
    scripts: LokiGrafanaScripts | None = None,
) -> None:
    """Install Loki and Grafana using the requested mode."""
    resolved = scripts or default_scripts()
    run_script(resolved.loki_install, ["--mode", mode])
    run_script(resolved.grafana_install, ["--mode", mode])


def remove_loki_grafana(
    *,
    remove_data: bool = False,
    scripts: LokiGrafanaScripts | None = None,
) -> None:
    """Remove Loki and Grafana using recorded install state."""
    resolved = scripts or default_scripts()
    remove_flag = "--remove-data" if remove_data else "--keep-data"
    run_script(resolved.loki_uninstall, [remove_flag])
    run_script(resolved.grafana_uninstall, [remove_flag])


def configure_grafana(
    *,
    grafana_url: str,
    grafana_api_key: str | None,
    grafana_org_id: int,
    loki_endpoint: str,
    assets: GrafanaAssets,
    client: GrafanaClient | None = None,
) -> GrafanaConfigSummary:
    """Configure Grafana with Loki and plugin-provided assets."""
    if client is None:
        if not grafana_api_key:
            raise ValueError("Grafana API key is required to configure assets")
        client = GrafanaClient(
            base_url=grafana_url,
            api_key=grafana_api_key,
            org_id=grafana_org_id,
        )

    ok, _ = client.health_check()
    if not ok:
        raise RuntimeError(f"Grafana is not reachable at {grafana_url}")

    loki_base = normalize_loki_base_url(loki_endpoint)
    loki_datasource_id = client.upsert_datasource(
        name=DEFAULT_LOKI_DATASOURCE_NAME,
        url=loki_base,
        datasource_type="loki",
        access="proxy",
        is_default=False,
    )
    if loki_datasource_id is None:
        raise RuntimeError("Grafana Loki datasource could not be created.")

    datasources_configured = 0
    for datasource in assets.datasources:
        url = datasource.url
        if not url:
            continue
        client.upsert_datasource(
            name=datasource.name,
            url=url,
            datasource_type=datasource.datasource_type,
            access=datasource.access,
            is_default=datasource.is_default,
            basic_auth=datasource.basic_auth,
            json_data=datasource.json_data,
        )
        datasources_configured += 1

    dashboards_configured = 0
    for dashboard_asset in assets.dashboards:
        dashboard = dashboard_asset.load()
        result = client.import_dashboard(dashboard, overwrite=True)
        if not result:
            raise RuntimeError("Grafana dashboard import failed.")
        dashboards_configured += 1

    return GrafanaConfigSummary(
        loki_datasource_id=loki_datasource_id,
        datasources_configured=datasources_configured,
        dashboards_configured=dashboards_configured,
    )
