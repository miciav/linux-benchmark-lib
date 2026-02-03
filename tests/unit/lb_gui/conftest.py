"""Pytest configuration for lb_gui tests."""

# Check if PySide6 is available at collection time
try:
    import PySide6  # noqa: F401

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

# Skip collection of test files if PySide6 is not available
if not HAS_PYSIDE6:
    collect_ignore = [
        "test_run_worker.py",
        "test_run_setup_vm.py",
        "test_dashboard_vm.py",
        "test_results_vm.py",
        "test_analytics_vm.py",
        "test_config_plugins_doctor_vm.py",
    ]
