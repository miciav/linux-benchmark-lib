"""Analytics package for transforming benchmark artifacts into profiles/reports."""

from lb_common import configure_logging as _configure_logging

_configure_logging()

from lb_analytics.aggregators.data_handler import DataHandler, TestResult
from lb_analytics.aggregators.collectors import aggregate_cli, aggregate_psutil
from lb_analytics.reporter import Reporter
from lb_analytics.analytics_service import AnalyticsRequest, AnalyticsService, AnalyticsKind

__all__ = [
    "DataHandler",
    "TestResult",
    "aggregate_psutil",
    "aggregate_cli",
    "Reporter",
    "AnalyticsRequest",
    "AnalyticsService",
    "AnalyticsKind",
]
