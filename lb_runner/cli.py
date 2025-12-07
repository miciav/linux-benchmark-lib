"""Runner CLI placeholder.

Delegates to the existing Typer application while runner packaging is
split out.
"""

from lb_ui.cli import app


def main() -> None:
    """Invoke the shared lb Typer application."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
