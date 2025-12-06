"""Controller CLI placeholder.

Delegates to the existing Typer application while controller packaging
is split out.
"""

from linux_benchmark_lib.cli import app


def main() -> None:
    """Invoke the shared lb Typer application."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
