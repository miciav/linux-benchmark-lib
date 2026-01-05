"""Provisioning helpers for Loki + Grafana."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from lb_app.services.config_service import ConfigService
from lb_controller.api import GrafanaPlatformConfig, LokiConfig
from lb_plugins.api import GrafanaAssets, collect_grafana_assets, create_registry
from lb_provisioner.api import (
    GrafanaConfigSummary,
    check_grafana_ready,
    check_loki_ready,
    configure_grafana,
    install_loki_grafana,
    remove_loki_grafana,
)


@dataclass(frozen=True)
class ProvisionStatus:
    """Health status for Loki and Grafana."""

    loki_url: str
    grafana_url: str
    loki_ready: bool
    grafana_ready: bool


@dataclass(frozen=True)
class ProvisionConfigSummary:
    """Summary of Grafana configuration."""

    loki_datasource_id: int | None
    datasources_configured: int
    dashboards_configured: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_grafana(
        cls,
        summary: GrafanaConfigSummary,
        warnings: tuple[str, ...] = (),
    ) -> "ProvisionConfigSummary":
        return cls(
            loki_datasource_id=summary.loki_datasource_id,
            datasources_configured=summary.datasources_configured,
            dashboards_configured=summary.dashboards_configured,
            warnings=warnings,
        )


class ProvisionService:
    """Provision Loki + Grafana and configure dashboards."""

    def __init__(self, config_service: ConfigService) -> None:
        self._config_service = config_service
        self._logger = logging.getLogger(__name__)

    def _resolve_platform_settings(
        self,
        *,
        grafana_url: str | None,
        grafana_api_key: str | None,
        grafana_org_id: int | None,
        loki_endpoint: str | None,
    ) -> tuple[str, str, str | None, int]:
        platform_cfg, _, _ = self._config_service.load_platform_config()
        resolved_loki = (
            loki_endpoint
            or (platform_cfg.loki.endpoint if platform_cfg.loki else None)
            or "http://localhost:3100"
        )
        resolved_grafana = (
            grafana_url
            or (platform_cfg.grafana.url if platform_cfg.grafana else None)
            or "http://localhost:3000"
        )
        resolved_api_key = (
            grafana_api_key
            or (platform_cfg.grafana.api_key if platform_cfg.grafana else None)
        )
        resolved_org_id = grafana_org_id or (
            platform_cfg.grafana.org_id if platform_cfg.grafana else 1
        )
        return resolved_loki, resolved_grafana, resolved_api_key, resolved_org_id

    def _persist_observability_defaults(
        self,
        *,
        loki_endpoint: str,
        grafana_url: str,
        grafana_api_key: str | None,
        grafana_org_id: int,
    ) -> None:
        platform_cfg, target = self._config_service.load_platform_for_write()
        updated = False

        if platform_cfg.loki:
            platform_cfg.loki.endpoint = loki_endpoint
            platform_cfg.loki.enabled = True
        else:
            platform_cfg.loki = LokiConfig(
                enabled=True,
                endpoint=loki_endpoint,
            )
        updated = True

        grafana_cfg = platform_cfg.grafana or GrafanaPlatformConfig()
        grafana_cfg.url = grafana_url
        grafana_cfg.org_id = grafana_org_id
        if grafana_api_key:
            grafana_cfg.api_key = grafana_api_key
        platform_cfg.grafana = grafana_cfg
        updated = True

        if updated:
            self._config_service.ensure_home()
            platform_cfg.save(target)

    def install_loki_grafana(
        self,
        *,
        mode: str,
        config_path: Path | None,
        grafana_url: str | None,
        grafana_api_key: str | None,
        grafana_admin_user: str | None,
        grafana_admin_password: str | None,
        grafana_token_name: str | None,
        grafana_org_id: int | None,
        loki_endpoint: str | None,
        configure_assets: bool = True,
    ) -> ProvisionConfigSummary | None:
        resolved_loki, resolved_grafana, resolved_api_key, resolved_org_id = (
            self._resolve_platform_settings(
                grafana_url=grafana_url,
                grafana_api_key=grafana_api_key,
                grafana_org_id=grafana_org_id,
                loki_endpoint=loki_endpoint,
            )
        )

        install_loki_grafana(mode=mode)

        self._persist_observability_defaults(
            loki_endpoint=resolved_loki,
            grafana_url=resolved_grafana,
            grafana_api_key=resolved_api_key,
            grafana_org_id=resolved_org_id,
        )

        if not configure_assets:
            return None
        if not resolved_api_key:
            if not grafana_admin_user:
                grafana_admin_user = "admin"
            if not grafana_admin_password:
                grafana_admin_password = "admin"

        platform_cfg, _, _ = self._config_service.load_platform_config()
        registry = create_registry()
        enabled_map = {
            name: platform_cfg.is_plugin_enabled(name)
            for name in registry.available(load_entrypoints=True)
        }
        warnings: list[str] = []
        assets: GrafanaAssets = GrafanaAssets()
        try:
            run_cfg, _, _ = self._config_service.load_for_read(config_path)
            assets = collect_grafana_assets(
                registry,
                plugin_settings=run_cfg.plugin_settings,
                enabled_plugins=enabled_map,
                remote_hosts=run_cfg.remote_hosts,
            )
        except Exception as exc:
            if config_path:
                raise
            warning = (
                "Skipping plugin Grafana assets because the default config "
                f"could not be loaded: {exc}. Provide --config to configure plugins."
            )
            self._logger.warning(warning)
            warnings.append(warning)

        summary = configure_grafana(
            grafana_url=resolved_grafana,
            grafana_api_key=resolved_api_key,
            grafana_admin_user=grafana_admin_user,
            grafana_admin_password=grafana_admin_password,
            grafana_token_name=grafana_token_name,
            grafana_org_id=resolved_org_id,
            loki_endpoint=resolved_loki,
            assets=assets,
        )
        return ProvisionConfigSummary.from_grafana(summary, warnings=tuple(warnings))

    def remove_loki_grafana(self, *, remove_data: bool = False) -> None:
        remove_loki_grafana(remove_data=remove_data)

    def status_loki_grafana(
        self,
        *,
        grafana_url: str | None,
        grafana_api_key: str | None,
        grafana_org_id: int | None,
        loki_endpoint: str | None,
    ) -> ProvisionStatus:
        resolved_loki, resolved_grafana, resolved_api_key, resolved_org_id = (
            self._resolve_platform_settings(
                grafana_url=grafana_url,
                grafana_api_key=grafana_api_key,
                grafana_org_id=grafana_org_id,
                loki_endpoint=loki_endpoint,
            )
        )
        loki_ok = check_loki_ready(resolved_loki)
        grafana_ok = check_grafana_ready(
            resolved_grafana,
            api_key=resolved_api_key,
            org_id=resolved_org_id,
        )
        return ProvisionStatus(
            loki_url=resolved_loki,
            grafana_url=resolved_grafana,
            loki_ready=loki_ok,
            grafana_ready=grafana_ok,
        )
