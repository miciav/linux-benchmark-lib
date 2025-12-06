"""UI facade for CLI/TUI components.

Provides a thin wrapper so UI code can evolve independently from
runner/controller packages.
"""

from lb_ui.cli import app
from lb_ui.ui.console_adapter import ConsoleUIAdapter
from lb_ui.ui.run_dashboard import RunDashboard

__all__ = ["app", "ConsoleUIAdapter", "RunDashboard"]
