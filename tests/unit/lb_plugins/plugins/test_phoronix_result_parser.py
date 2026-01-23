from __future__ import annotations

import pytest

from lb_plugins.plugins.phoronix_test_suite.plugin import PtsResultParser

pytestmark = [pytest.mark.unit_plugins]


def test_pts_result_parser_normalizes_failure_marker() -> None:
    parser = PtsResultParser("pts-profile")

    rc = parser.normalize_returncode(
        0,
        "the batch mode must first be configured",
    )

    assert rc == 2


def test_pts_result_parser_builds_success_result() -> None:
    parser = PtsResultParser("pts-profile")

    result = parser.build_success_result(
        ["pts", "run"],
        0,
        "ok",
        "/tmp/pts-results",
        "result-id",
        0.0,
    )

    assert result["profile"] == "pts-profile"
    assert result["returncode"] == 0
