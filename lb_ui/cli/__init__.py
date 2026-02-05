import subprocess

from .main import app, ctx_store, main

__all__ = ["app", "main", "ctx_store"]

# Accessors for testing compatibility (monkeypatching)
# These map back to the global ctx_store in the main module.


def __getattr__(name):
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


def __setattr__(name, value):
    if name in (
        "config_service",
        "doctor_service",
        "test_service",
        "analytics_service",
        "app_client",
        "ui",
        "ui_adapter",
    ):
        setattr(ctx_store, name, value)
    elif name == "DEV_MODE":
        ctx_store.dev_mode = value
    elif name == "subprocess":
        import sys

        module = sys.modules[__name__]
        # We need to monkeypatch the module level attribute for test expectations
        object.__setattr__(module, "subprocess", value)
    else:
        super().__setattr__(name, value)
