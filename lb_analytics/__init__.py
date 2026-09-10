"""Analytics package for transforming benchmark artifacts into profiles/reports."""

from lb_common.api import configure_logging as _configure_logging

_configure_logging()

from lb_analytics.api import (  # noqa: E402
    AnalyticsKind,
    AnalyticsRequest,
    AnalyticsService,
    DataHandler,
    Reporter,
    TestResult,
    aggregate_cli,
    aggregate_psutil,
)

__all__ = [
    "AnalyticsKind",
    "AnalyticsRequest",
    "AnalyticsService",
    "DataHandler",
    "Reporter",
    "TestResult",
    "aggregate_cli",
    "aggregate_psutil",
]
