"""Controller CLI placeholder.

This entrypoint intentionally avoids importing the UI layer. The
user-facing CLI lives in lb_ui.
"""


def main() -> None:
    """Inform users to invoke the UI package for CLI functionality."""
    raise SystemExit("Controller CLI is deprecated. Use `python -m lb_ui.cli` instead.")


if __name__ == "__main__":  # pragma: no cover
    main()
