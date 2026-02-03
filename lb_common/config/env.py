"""Environment variable parsing utilities."""

from __future__ import annotations


def parse_bool_env(value: str | None) -> bool | None:
    """Parse a boolean from an environment variable string.

    Returns True for "1", "true", "yes", "on" (case-insensitive).
    Returns None if value is None.
    """
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_int_env(value: str | None) -> int | None:
    """Parse an integer from an environment variable string.

    Returns None if value is None or cannot be parsed.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_float_env(value: str | None) -> float | None:
    """Parse a float from an environment variable string.

    Returns None if value is None or cannot be parsed.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_labels_env(value: str | None) -> dict[str, str]:
    """Parse a comma-separated key=value string into a dict.

    Example: "env=prod,region=us-east" -> {"env": "prod", "region": "us-east"}
    Returns an empty dict if value is None or empty.
    """
    labels: dict[str, str] = {}
    if not value:
        return labels
    for token in value.split(","):
        token = token.strip()
        if not token or "=" not in token:
            continue
        key, raw_value = token.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            continue
        labels[key] = raw_value
    return labels
