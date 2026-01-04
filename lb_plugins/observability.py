"""Grafana observability assets provided by workload plugins."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class GrafanaDatasourceAsset:
    """Grafana datasource definition with optional config-driven URL."""

    name: str
    datasource_type: str = "prometheus"
    access: str = "proxy"
    is_default: bool = False
    url: str | None = None
    url_from_config: str | None = None
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
) -> GrafanaAssets:
    """Resolve datasource URLs using the provided plugin config."""
    resolved: list[GrafanaDatasourceAsset] = []
    for datasource in assets.datasources:
        resolved_ds = datasource.resolve(config)
        if resolved_ds is not None:
            resolved.append(resolved_ds)
    return GrafanaAssets(datasources=tuple(resolved), dashboards=tuple(assets.dashboards))

