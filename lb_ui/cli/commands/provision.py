from __future__ import annotations

from typing import Optional, Literal
from pathlib import Path

import typer

from lb_plugins.api import collect_grafana_assets, create_registry
from lb_provisioner.api import (
    check_grafana_ready,
    check_loki_ready,
    configure_grafana,
    install_loki_grafana,
    remove_loki_grafana,
)
from lb_ui.wiring.dependencies import UIContext


def create_provision_app(ctx: UIContext) -> typer.Typer:
    """Build the provision Typer app (observability services)."""
    app = typer.Typer(help="Install and configure observability services.", no_args_is_help=True)

    loki_grafana_app = typer.Typer(help="Provision Loki + Grafana together.")

    @loki_grafana_app.command("install")
    def loki_grafana_install(
        mode: Literal["local", "docker"] = typer.Option(
            "local",
            "--mode",
            "-m",
            help="Install mode: local (brew/apt) or docker.",
        ),
        config: Optional[Path] = typer.Option(
            None,
            "--config",
            "-c",
            help="Run config to resolve plugin settings for dashboards.",
        ),
        grafana_url: Optional[str] = typer.Option(
            None,
            "--grafana-url",
            help="Grafana base URL (defaults to platform config or localhost).",
        ),
        grafana_api_key: Optional[str] = typer.Option(
            None,
            "--grafana-api-key",
            help="Grafana API key used to configure datasources/dashboards.",
        ),
        grafana_org_id: Optional[int] = typer.Option(
            None,
            "--grafana-org-id",
            help="Grafana organization id.",
        ),
        loki_endpoint: Optional[str] = typer.Option(
            None,
            "--loki-endpoint",
            help="Loki base URL or push endpoint.",
        ),
        configure_assets: bool = typer.Option(
            True,
            "--configure/--no-configure",
            help="Configure Grafana datasources and dashboards after install.",
        ),
    ) -> None:
        platform_cfg, _, _ = ctx.config_service.load_platform_config()
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

        ctx.ui.present.info("Installing Loki and Grafana...")
        try:
            install_loki_grafana(mode=mode)
        except Exception as exc:
            ctx.ui.present.error(f"Installation failed: {exc}")
            raise typer.Exit(1)

        if not configure_assets:
            ctx.ui.present.warning("Skipping Grafana configuration (--no-configure).")
            return

        if not resolved_api_key:
            ctx.ui.present.error(
                "Grafana API key required to configure datasources/dashboards. "
                "Provide --grafana-api-key or set it in platform config."
            )
            raise typer.Exit(1)

        registry = create_registry()
        enabled_map = {
            name: platform_cfg.is_plugin_enabled(name)
            for name in registry.available(load_entrypoints=True)
        }
        if config:
            run_cfg, _, _ = ctx.config_service.load_for_read(config)
        else:
            run_cfg = ctx.config_service.create_default_config()
        assets = collect_grafana_assets(
            registry,
            plugin_settings=run_cfg.plugin_settings,
            enabled_plugins=enabled_map,
        )

        ctx.ui.present.info("Configuring Grafana datasources and dashboards...")
        try:
            summary = configure_grafana(
                grafana_url=resolved_grafana,
                grafana_api_key=resolved_api_key,
                grafana_org_id=resolved_org_id,
                loki_endpoint=resolved_loki,
                assets=assets,
            )
        except Exception as exc:
            ctx.ui.present.error(f"Grafana configuration failed: {exc}")
            raise typer.Exit(1)

        ctx.ui.present.success(
            "Grafana configured: "
            f"{summary.datasources_configured} datasource(s), "
            f"{summary.dashboards_configured} dashboard(s)."
        )

    @loki_grafana_app.command("remove")
    def loki_grafana_remove(
        remove_data: bool = typer.Option(
            False,
            "--remove-data",
            help="Remove Loki/Grafana data directories as well.",
        ),
    ) -> None:
        ctx.ui.present.info("Removing Loki and Grafana...")
        try:
            remove_loki_grafana(remove_data=remove_data)
        except Exception as exc:
            ctx.ui.present.error(f"Removal failed: {exc}")
            raise typer.Exit(1)
        ctx.ui.present.success("Loki and Grafana removed.")

    @loki_grafana_app.command("status")
    def loki_grafana_status(
        grafana_url: Optional[str] = typer.Option(
            None,
            "--grafana-url",
            help="Grafana base URL (defaults to platform config or localhost).",
        ),
        grafana_api_key: Optional[str] = typer.Option(
            None,
            "--grafana-api-key",
            help="Grafana API key for authenticated health checks.",
        ),
        grafana_org_id: Optional[int] = typer.Option(
            None,
            "--grafana-org-id",
            help="Grafana organization id.",
        ),
        loki_endpoint: Optional[str] = typer.Option(
            None,
            "--loki-endpoint",
            help="Loki base URL or push endpoint.",
        ),
    ) -> None:
        platform_cfg, _, _ = ctx.config_service.load_platform_config()
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

        loki_ok = check_loki_ready(resolved_loki)
        grafana_ok = check_grafana_ready(
            resolved_grafana,
            api_key=resolved_api_key,
            org_id=resolved_org_id,
        )

        if loki_ok:
            ctx.ui.present.success(f"Loki ready: {resolved_loki}")
        else:
            ctx.ui.present.warning(f"Loki not reachable: {resolved_loki}")

        if grafana_ok:
            ctx.ui.present.success(f"Grafana ready: {resolved_grafana}")
        else:
            ctx.ui.present.warning(f"Grafana not reachable: {resolved_grafana}")

        if not (loki_ok and grafana_ok):
            raise typer.Exit(1)

    app.add_typer(loki_grafana_app, name="loki-grafana")
    return app
