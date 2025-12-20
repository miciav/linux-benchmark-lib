"""Stable application-layer API surface."""

from lb_app.client import ApplicationClient
from lb_app.interfaces import AppClient, RunRequest, UIHooks
from lb_app.services.doctor_service import DoctorService
from lb_app.services.doctor_types import (
    DoctorCheckGroup,
    DoctorCheckItem,
    DoctorReport,
)
from lb_app.services.run_types import RunResult
from lb_app.services.test_service import TestService
from lb_app.ui_interfaces import (
    DashboardHandle,
    NoOpDashboardHandle,
    NoOpProgressHandle,
    NoOpUIAdapter,
    ProgressHandle,
    UIAdapter,
)

__all__ = [
    "AppClient",
    "ApplicationClient",
    "UIHooks",
    "RunRequest",
    "RunResult",
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
]
