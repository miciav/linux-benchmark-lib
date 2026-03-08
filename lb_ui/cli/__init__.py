import subprocess
from typing import Any

from .main import app, ctx_store, main

__all__ = ["app", "main", "ctx_store"]

# Accessors for testing compatibility (monkeypatching)
# These map back to the global ctx_store in the main module.


def __getattr__(name: str) -> Any:
    if name == "config_service":
        return ctx_store.config_service
    if name == "doctor_service":
        return ctx_store.doctor_service
    if name == "test_service":
        return ctx_store.test_service
    if name == "analytics_service":
        return ctx_store.analytics_service
    if name == "app_client":
        return ctx_store.app_client
    if name == "ui":
        return ctx_store.ui
    if name == "ui_adapter":
        return ctx_store.ui_adapter
    if name == "DEV_MODE":
        return ctx_store.dev_mode
    if name == "subprocess":
        return subprocess
    raise AttributeError(f"module {__name__} has no attribute {name}")
