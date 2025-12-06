"""UI facade for CLI/TUI components.

Provides a thin wrapper so UI code can evolve independently from
runner/controller packages.
"""

from linux_benchmark_lib.cli import app
from linux_benchmark_lib.ui.console_adapter import ConsoleUIAdapter
from linux_benchmark_lib.ui.run_dashboard import RunDashboard

__all__ = ["app", "ConsoleUIAdapter", "RunDashboard"]
