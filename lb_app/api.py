"""Stable application-layer API surface."""

from lb_app.client import ApplicationClient
from lb_app.interfaces import AppClient, RunRequest, UIHooks
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
from lb_app.services.run_service import RunService
from lb_app.services.run_types import RunContext, RunResult
from lb_app.services.test_service import TestService
from lb_app.services.run_output import AnsibleOutputFormatter, _extract_lb_event_data
from lb_app.services.run_system_info import summarize_system_info
from lb_app.services import run_service as run_service_module
from lb_app.services import test_service as test_service_module
from lb_app.ui_interfaces import (
    DashboardHandle,
    NoOpDashboardHandle,
    NoOpProgressHandle,
    NoOpUIAdapter,
    ProgressHandle,
    UIAdapter,
)
from lb_controller.api import (
    BenchmarkConfig,
    RunCatalogService,
    RunExecutionSummary,
    RunEvent,
    RunJournal,
    RunStatus,
    TaskState,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_plugins.api import PluginRegistry, WorkloadIntensity, build_plugin_table, create_registry
from lb_analytics.api import AnalyticsRequest, AnalyticsService, AnalyticsKind
from lb_common.api import RemoteHostSpec, RunInfo
from lb_provisioner.api import MAX_NODES

__all__ = [
    "AppClient",
    "ApplicationClient",
    "UIHooks",
    "RunRequest",
    "RunContext",
    "RunResult",
    "RunService",
    "AnsibleOutputFormatter",
    "_extract_lb_event_data",
    "summarize_system_info",
    "run_service_module",
    "test_service_module",
    "UIAdapter",
    "DashboardHandle",
    "ProgressHandle",
    "NoOpUIAdapter",
    "NoOpDashboardHandle",
    "NoOpProgressHandle",
    "DoctorService",
    "DoctorCheckGroup",
    "DoctorCheckItem",
    "DoctorReport",
    "TestService",
    "ProvisionConfigSummary",
    "ProvisionService",
    "ProvisionStatus",
    "BenchmarkConfig",
    "ConfigService",
    "PluginRegistry",
    "RunCatalogService",
    "RunEvent",
    "RunJournal",
    "RunStatus",
    "TaskState",
    "RemoteHostConfig",
    "WorkloadConfig",
    "WorkloadIntensity",
    "RunExecutionSummary",
    "build_plugin_table",
    "create_registry",
    "AnalyticsRequest",
    "AnalyticsService",
    "AnalyticsKind",
    "RemoteHostSpec",
    "RunInfo",
    "MAX_NODES",
]
