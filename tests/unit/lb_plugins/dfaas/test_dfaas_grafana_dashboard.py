import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit_plugins]

DASHBOARD_PATH = Path("lb_plugins/plugins/dfaas/grafana/dfaas-dashboard.json")


def _load_dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text())


def test_default_dashboard_json_valid() -> None:
    data = _load_dashboard()

    assert data["title"] == "DFaaS Overview"
    panels = data.get("panels", [])
    panel_titles = {panel.get("title") for panel in panels}
    assert "Node CPU Usage (%)" in panel_titles
    assert "Request Success Rate (%)" in panel_titles
    assert "Throughput by Function (req/s)" in panel_titles
    assert "Latency Heatmap by Function" in panel_titles
    assert "Overload Events Timeline" in panel_titles

    templating = data.get("templating", {}).get("list", [])
    templating_names = {template.get("name") for template in templating}
    assert {"datasource", "run_id", "host", "function"} <= templating_names


def test_dashboard_uses_dfaas_metrics() -> None:
    """Dashboard queries should use efficient dfaas_* metric names."""
    data = _load_dashboard()
    panels = data.get("panels", [])

    dfaas_panels = [
        p
        for p in panels
        if p.get("title")
        in {
            "Request Success Rate (%)",
            "Throughput by Function (req/s)",
            "Latency Heatmap by Function",
            "Overload Events Timeline",
        }
    ]
    assert len(dfaas_panels) == 4

    for panel in dfaas_panels:
        targets = panel.get("targets", [])
        assert targets, f"Panel {panel['title']} has no targets"
        for target in targets:
            expr = target.get("expr", "")
            assert (
                "__name__" not in expr
            ), f"Panel '{panel['title']}' uses inefficient __name__ matcher: {expr}"
            assert (
                "dfaas_" in expr
            ), f"Panel '{panel['title']}' should use dfaas_* metrics: {expr}"


def test_dashboard_template_queries_use_dfaas_metrics() -> None:
    """Template variable queries should use dfaas_* metrics for efficiency."""
    data = _load_dashboard()
    templating = data.get("templating", {}).get("list", [])

    run_id_var = next((t for t in templating if t.get("name") == "run_id"), None)
    assert run_id_var is not None
    assert "dfaas_success_rate" in run_id_var.get("query", "")
    assert "__name__" not in run_id_var.get("query", "")

    function_var = next((t for t in templating if t.get("name") == "function"), None)
    assert function_var is not None
    assert "dfaas_success_rate" in function_var.get("query", "")
    assert "__name__" not in function_var.get("query", "")


def test_dashboard_has_required_panels() -> None:
    """Dashboard should have all required panels for DFaaS monitoring."""
    data = _load_dashboard()
    panels = data.get("panels", [])

    required_panels = {
        "Node CPU Usage (%)",
        "Node RAM Usage (bytes)",
        "Node RAM Usage (%)",
        "Node Power (W)",
        "Request Success Rate (%)",
        "Throughput by Function (req/s)",
        "Latency Heatmap by Function",
        "Overload Events Timeline",
    }

    panel_titles = {p.get("title") for p in panels}
    missing = required_panels - panel_titles
    assert not missing, f"Missing required panels: {missing}"
