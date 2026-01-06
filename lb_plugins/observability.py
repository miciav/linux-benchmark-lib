"""Grafana observability assets provided by workload plugins."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from lb_common.models.hosts import RemoteHostSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GrafanaDatasourceAsset:
    """Grafana datasource definition with optional config-driven URL."""

    name: str
    datasource_type: str = "prometheus"
    access: str = "proxy"
    is_default: bool = False
    url: str | None = None
    url_from_config: str | None = None
    url_template: str | None = None
    name_template: str | None = None
    per_host: bool = False
    basic_auth: tuple[str, str] | None = None
    json_data: Mapping[str, Any] | None = None

    def resolve_url(self, config: Any | Mapping[str, Any] | None) -> str | None:
        """Resolve the datasource URL from explicit value or config field."""
        if self.url:
            return self.url
        if not self.url_from_config or config is None:
            return None
        if isinstance(config, Mapping):
            value = config.get(self.url_from_config)
        else:
            value = getattr(config, self.url_from_config, None)
        if value is None:
            return None
        value_str = str(value).strip()
        return value_str or None

    def resolve(self, config: Any | Mapping[str, Any] | None) -> "GrafanaDatasourceAsset | None":
        """Return a copy with URL populated, or None if unavailable."""
        url = self.resolve_url(config)
        if not url:
            return None
        return replace(self, url=url)


@dataclass(frozen=True)
class GrafanaDashboardAsset:
    """Grafana dashboard definition backed by JSON content or a file path."""

    name: str
    path: Path | None = None
    dashboard: Mapping[str, Any] | None = None

    def load(self) -> Mapping[str, Any]:
        """Load the dashboard JSON from inline content or a file path."""
        if self.dashboard is not None:
            return dict(self.dashboard)
        if not self.path:
            raise ValueError("Grafana dashboard asset missing path or inline content")
        return json.loads(self.path.read_text())


@dataclass(frozen=True)
class GrafanaAssets:
    """Grafana datasources and dashboards bundled by a plugin."""

    datasources: Sequence[GrafanaDatasourceAsset] = ()
    dashboards: Sequence[GrafanaDashboardAsset] = ()


def resolve_grafana_assets(
    assets: GrafanaAssets,
    config: Any | Mapping[str, Any] | None,
    hosts: Sequence[Any] | None = None,
) -> GrafanaAssets:
    """Resolve datasource URLs using the provided plugin config."""
    resolved: list[GrafanaDatasourceAsset] = []
    host_specs: list[RemoteHostSpec] = []
    if hosts:
        host_specs = [RemoteHostSpec.from_object(host) for host in hosts]
    cfg_context = _to_namespace(config)
    for datasource in assets.datasources:
        resolved_ds = datasource.resolve(config)
        if resolved_ds is not None:
            if resolved_ds.per_host and host_specs:
                resolved.extend(
                    _expand_per_host_datasource(resolved_ds, host_specs, cfg_context)
                )
            else:
                resolved.append(resolved_ds)
    return GrafanaAssets(datasources=tuple(resolved), dashboards=tuple(assets.dashboards))


def _expand_per_host_datasource(
    datasource: GrafanaDatasourceAsset,
    hosts: Sequence[RemoteHostSpec],
    config: Any | None,
) -> list[GrafanaDatasourceAsset]:
    expanded: list[GrafanaDatasourceAsset] = []
    name_template = datasource.name_template or "{name}-{host.name}"
    url_template = datasource.url_template or datasource.url or ""
    if len(hosts) > 1 and not _template_has_host_placeholder(
        url_template, datasource, hosts[0], config
    ):
        logger.warning(
            "Skipping Grafana datasource %s: per_host requires a {host.*} template",
            datasource.name,
        )
        return []
    for host in hosts:
        name = _format_template(name_template, datasource, host, config)
        url = _format_template(url_template, datasource, host, config)
        if "{host" in url or "{config" in url or "{name" in url:
            url = _format_template(url, datasource, host, config)
        if not url:
            continue
        expanded.append(
            replace(
                datasource,
                name=name,
                url=url,
                per_host=False,
                name_template=None,
                url_template=None,
            )
        )
    return expanded


def _format_template(
    template: str,
    datasource: GrafanaDatasourceAsset,
    host: RemoteHostSpec,
    config: Any | None,
) -> str:
    try:
        return template.format(
            host=host,
            config=config,
            name=datasource.name,
        )
    except Exception:
        return template


def _to_namespace(config: Any | Mapping[str, Any] | None) -> Any | None:
    if config is None:
        return None
    if isinstance(config, Mapping):
        return SimpleNamespace(**config)
    return config

def _template_has_host_placeholder(
    template: str,
    datasource: GrafanaDatasourceAsset,
    host: RemoteHostSpec,
    config: Any | None,
) -> bool:
    if "{host" in template:
        return True
    if "{config" in template or "{name" in template:
        resolved = _format_template(template, datasource, host, config)
        return "{host" in resolved
    return False
