from __future__ import annotations

from typing import Optional, Literal
from pathlib import Path

import typer

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
        grafana_admin_user: Optional[str] = typer.Option(
            None,
            "--grafana-admin-user",
            help="Grafana admin user to create an API key automatically (default: admin).",
        ),
        grafana_admin_password: Optional[str] = typer.Option(
            None,
            "--grafana-admin-password",
            help="Grafana admin password to create an API key automatically (default: admin).",
        ),
        grafana_token_name: Optional[str] = typer.Option(
            None,
            "--grafana-api-key-name",
            help="Name for the generated Grafana API key/token.",
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
        ctx.ui.present.info("Installing Loki and Grafana...")
        try:
            summary = ctx.app_client.install_loki_grafana(
                mode=mode,
                config_path=config,
                grafana_url=grafana_url,
                grafana_api_key=grafana_api_key,
                grafana_admin_user=grafana_admin_user,
                grafana_admin_password=grafana_admin_password,
                grafana_token_name=grafana_token_name,
                grafana_org_id=grafana_org_id,
                loki_endpoint=loki_endpoint,
                configure_assets=configure_assets,
            )
        except Exception as exc:
            ctx.ui.present.error(f"Installation failed: {exc}")
            raise typer.Exit(1)

        if not configure_assets:
            ctx.ui.present.warning("Skipping Grafana configuration (--no-configure).")
            return
        if summary is None:
            ctx.ui.present.warning("Grafana configuration skipped.")
            return

        ctx.ui.present.success(
            "Grafana configured: "
            f"{summary.datasources_configured} datasource(s), "
            f"{summary.dashboards_configured} dashboard(s)."
        )
        for warning in summary.warnings:
            ctx.ui.present.warning(warning)

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
            ctx.app_client.remove_loki_grafana(remove_data=remove_data)
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
        status = ctx.app_client.status_loki_grafana(
            grafana_url=grafana_url,
            grafana_api_key=grafana_api_key,
            grafana_org_id=grafana_org_id,
            loki_endpoint=loki_endpoint,
        )

        if status.loki_ready:
            ctx.ui.present.success(f"Loki ready: {status.loki_url}")
        else:
            ctx.ui.present.warning(f"Loki not reachable: {status.loki_url}")

        if status.grafana_ready:
            ctx.ui.present.success(f"Grafana ready: {status.grafana_url}")
        else:
            ctx.ui.present.warning(f"Grafana not reachable: {status.grafana_url}")

        if not (status.loki_ready and status.grafana_ready):
            raise typer.Exit(1)

    app.add_typer(loki_grafana_app, name="loki-grafana")
    return app
