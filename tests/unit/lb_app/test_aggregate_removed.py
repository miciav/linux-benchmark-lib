import importlib

import pytest

pytestmark = pytest.mark.unit_analytics

GONE = {
    "lb_app.api": ["AnalyticsKind", "AnalyticsRequest", "AnalyticsService"],
    "lb_analytics.api": [
        "AnalyticsService",
        "DataHandler",
        "Reporter",
        "TestResult",
        "aggregate_cli",
        "aggregate_psutil",
    ],
    "lb_runner.api": ["aggregate_cli"],
}


@pytest.mark.parametrize("module", sorted(GONE))
def test_the_per_run_aggregate_analytics_is_gone(module):
    api = importlib.import_module(module)
    assert [name for name in GONE[module] if hasattr(api, name)] == []
