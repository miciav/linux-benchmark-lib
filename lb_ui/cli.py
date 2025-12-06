"""UI CLI module (moved from linux_benchmark_lib.cli)."""

from lb_controller.services.plugin_service import create_registry
from lb_controller.services.run_service import RunService
from lb_controller.services.setup_service import SetupService
from lb_controller.services.test_service import TestService
from lb_controller.services.config_service import ConfigService
from lb_controller.services.multipass_service import MultipassService
from lb_controller.services.container_service import ContainerRunner
from lb_controller.services.doctor_service import DoctorService
from lb_controller.data_handler import DataHandler
from lb_runner import BenchmarkConfig
from lb_runner.plugin_system.builtin import builtin_plugins
from lb_runner.plugin_system.registry import PluginRegistry
from lb_ui.ui.console_adapter import ConsoleUIAdapter
from lb_ui.ui.types import UIAdapter

# Import the original Typer app to preserve behavior.
from linux_benchmark_lib.cli import app  # type: ignore  # noqa: E402

__all__ = [
    "app",
    "create_registry",
    "RunService",
    "SetupService",
    "TestService",
    "ConfigService",
    "MultipassService",
    "ContainerRunner",
    "DoctorService",
    "DataHandler",
    "BenchmarkConfig",
    "builtin_plugins",
    "PluginRegistry",
    "ConsoleUIAdapter",
    "UIAdapter",
]


def main() -> None:
    """Invoke the Typer CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
