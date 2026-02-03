"""Tests for shared error helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from lb_common.errors import WorkloadError, error_to_payload


pytestmark = pytest.mark.unit_runner


def test_error_to_payload_normalizes_context() -> None:
    err = WorkloadError(
        "boom",
        context={
            "path": Path("/tmp/test"),
            "count": 3,
            "nested": {"value": Path("nested")},
            "items": [Path("a"), "b"],
        },
    )
    payload = error_to_payload(err)
    assert payload["error_type"] == "WorkloadError"
    assert payload["error"] == "boom"
    assert payload["error_context"]["path"].endswith("test")
    assert payload["error_context"]["count"] == 3
    assert payload["error_context"]["nested"]["value"] == "nested"
    assert payload["error_context"]["items"][0] == "a"
