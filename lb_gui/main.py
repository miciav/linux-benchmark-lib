"""Console entrypoint for the GUI (lb gui)."""

from __future__ import annotations

import sys


def main() -> int:
    """Launch the GUI application."""
    # Configure logging before anything else
    from lb_common.api import configure_logging

    configure_logging()

    # Import Qt after logging is configured
    from PySide6.QtWidgets import QApplication

    from lb_gui.app import create_app
    from lb_gui.resources.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("Linux Benchmark")
    app.setOrganizationName("lb")

    apply_theme(app)

    window = create_app()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
