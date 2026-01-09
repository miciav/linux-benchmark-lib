"""Tests for app client API surface."""

import pytest

from lb_app.api import AppClient, ApplicationClient


pytestmark = pytest.mark.unit_ui


def test_app_client_aliases_application_client() -> None:
    assert AppClient is ApplicationClient
    for name in (
        "load_config",
        "save_config",
        "list_runs",
        "get_run_plan",
        "start_run",
        "install_loki_grafana",
        "remove_loki_grafana",
        "status_loki_grafana",
    ):
        assert hasattr(ApplicationClient, name)
