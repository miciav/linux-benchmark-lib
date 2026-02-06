from __future__ import annotations

import pytest

from lb_plugins.plugins.peva_faas.exceptions import (
    ConfigExecutionError,
    ConfigSkippedError,
    DfaasError,
    IndexLoadError,
    K6ExecutionError,
)

pytestmark = [pytest.mark.unit_plugins]


def test_dfaas_error_is_base_exception() -> None:
    err = DfaasError("base")
    assert str(err) == "base"


def test_k6_execution_error_exposes_context() -> None:
    err = K6ExecutionError("cfg-1", "bad status", stdout="ok", stderr="trace")

    assert err.config_id == "cfg-1"
    assert err.stdout == "ok"
    assert err.stderr == "trace"
    assert "k6 execution failed for config cfg-1: bad status" in str(err)


def test_config_execution_error_formats_with_optional_cause() -> None:
    without_cause = ConfigExecutionError("cfg-2")
    with_cause = ConfigExecutionError("cfg-2", RuntimeError("boom"))

    assert str(without_cause) == "Configuration cfg-2 failed"
    assert str(with_cause) == "Configuration cfg-2 failed: boom"
    assert with_cause.config_id == "cfg-2"
    assert isinstance(with_cause.cause, RuntimeError)


def test_config_skipped_error_contains_reason() -> None:
    err = ConfigSkippedError("cfg-3", "cooldown timeout")

    assert err.config_id == "cfg-3"
    assert err.reason == "cooldown timeout"
    assert str(err) == "Configuration cfg-3 skipped: cooldown timeout"


def test_index_load_error_formats_with_optional_cause() -> None:
    without_cause = IndexLoadError("/tmp/index.csv")
    with_cause = IndexLoadError("/tmp/index.csv", ValueError("bad file"))

    assert without_cause.path == "/tmp/index.csv"
    assert str(without_cause) == "Failed to load index from /tmp/index.csv"
    assert str(with_cause) == "Failed to load index from /tmp/index.csv: bad file"
