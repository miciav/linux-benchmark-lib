"""Stable application-layer API surface."""

from lb_analytics.api import AnalyticsKind, AnalyticsRequest, AnalyticsService
from lb_app.client import ApplicationClient
from lb_app.interfaces import RunRequest, UIHooks
from lb_app.services import run_service as run_service_module
from lb_app.services import test_service as test_service_module
from lb_app.services.config_service import ConfigService
from lb_app.services.doctor_service import DoctorService
from lb_app.services.doctor_types import (
    DoctorCheckGroup,
    DoctorCheckItem,
    DoctorReport,
)
from lb_app.services.provision_service import (
    ProvisionConfigSummary,
    ProvisionService,
    ProvisionStatus,
)
from lb_app.services.run_journal import generate_run_id, results_exist_for_run
from lb_app.services.run_output import AnsibleOutputFormatter, _extract_lb_event_data
from lb_app.services.run_service import RunService
from lb_app.services.run_system_info import summarize_system_info
from lb_app.services.run_types import RunContext, RunResult
from lb_app.services.test_service import TestService
from lb_app.ui_interfaces import (
    DashboardHandle,
    NoOpDashboardHandle,
    NoOpProgressHandle,
    NoOpUIAdapter,
    ProgressHandle,
    UIAdapter,
)
from lb_app.viewmodels.dashboard import (
    DashboardLogMetadata,
    DashboardRow,
    DashboardSnapshot,
    DashboardStatusSummary,
    DashboardViewModel,
    build_dashboard_viewmodel,
    event_status_line,
)
from lb_app.viewmodels.run_viewmodels import (
    journal_rows,
    plan_rows,
    summarize_progress,
    target_repetitions,
)
from lb_common.api import RemoteHostSpec, RunInfo
from lb_controller.api import (
    BenchmarkConfig,
    PlatformConfig,
    RemoteHostConfig,
    RunCatalogService,
    RunEvent,
    RunExecutionSummary,
    RunJournal,
    RunStatus,
    TaskState,
    WorkloadConfig,
)
from lb_plugins.api import (
    PluginRegistry,
    WorkloadIntensity,
    build_plugin_table,
    create_registry,
    reset_registry_cache,
)
from lb_provisioner.api import MAX_NODES

AppClient = ApplicationClient

__all__ = [
    "MAX_NODES",
    "AnalyticsKind",
    "AnalyticsRequest",
    "AnalyticsService",
    "AnsibleOutputFormatter",
    "AppClient",
    "ApplicationClient",
    "BenchmarkConfig",
    "ConfigService",
    "DashboardHandle",
    "DashboardLogMetadata",
    "DashboardRow",
    "DashboardSnapshot",
    "DashboardStatusSummary",
    "DashboardViewModel",
    "DoctorCheckGroup",
    "DoctorCheckItem",
    "DoctorReport",
    "DoctorService",
    "NoOpDashboardHandle",
    "NoOpProgressHandle",
    "NoOpUIAdapter",
    "PlatformConfig",
    "PluginRegistry",
    "ProgressHandle",
    "ProvisionConfigSummary",
    "ProvisionService",
    "ProvisionStatus",
    "RemoteHostConfig",
    "RemoteHostSpec",
    "RunCatalogService",
    "RunContext",
    "RunEvent",
    "RunExecutionSummary",
    "RunInfo",
    "RunJournal",
    "RunRequest",
    "RunResult",
    "RunService",
    "RunStatus",
    "TaskState",
    "TestService",
    "UIAdapter",
    "UIHooks",
    "WorkloadConfig",
    "WorkloadIntensity",
    "_extract_lb_event_data",
    "build_dashboard_viewmodel",
    "build_plugin_table",
    "create_registry",
    "event_status_line",
    "generate_run_id",
    "journal_rows",
    "plan_rows",
    "reset_registry_cache",
    "results_exist_for_run",
    "run_service_module",
    "summarize_progress",
    "summarize_system_info",
    "target_repetitions",
    "test_service_module",
]
