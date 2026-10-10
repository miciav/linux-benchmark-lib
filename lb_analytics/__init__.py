"""Analytics package: unify benchmark experiment datasets into tables."""

from lb_common.api import configure_logging as _configure_logging

_configure_logging()

from lb_analytics.api import ExperimentData, LoadReport, load_experiment  # noqa: E402

__all__ = ["ExperimentData", "LoadReport", "load_experiment"]
