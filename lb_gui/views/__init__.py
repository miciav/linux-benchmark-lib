"""GUI views (Qt widgets for each section)."""

from lb_gui.views.analytics_view import AnalyticsView
from lb_gui.views.config_view import ConfigView
from lb_gui.views.dashboard_view import DashboardView
from lb_gui.views.doctor_view import DoctorView
from lb_gui.views.plugins_view import PluginsView
from lb_gui.views.results_view import ResultsView
from lb_gui.views.run_setup_view import RunSetupView

__all__ = [
    "AnalyticsView",
    "ConfigView",
    "DashboardView",
    "DoctorView",
    "PluginsView",
    "ResultsView",
    "RunSetupView",
]
