"""Tests for Loki env fallbacks in config."""

from __future__ import annotations

import pytest

from lb_runner.models.config import LokiConfig


pytestmark = pytest.mark.unit_runner


def test_loki_env_fallbacks_apply_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LB_LOKI_ENABLED", "1")
    monkeypatch.setenv("LB_LOKI_ENDPOINT", "http://env-loki")
    monkeypatch.setenv("LB_LOKI_BATCH_SIZE", "250")

    cfg = LokiConfig.model_validate({})

    assert cfg.enabled is True
    assert cfg.endpoint == "http://env-loki"
    assert cfg.batch_size == 250


def test_loki_env_fallbacks_do_not_override_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LB_LOKI_ENABLED", "0")
    cfg = LokiConfig(enabled=True)

    assert cfg.enabled is True


def test_loki_env_labels_merge_with_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LB_LOKI_LABELS", "env=1,shared=env")

    cfg = LokiConfig(labels={"shared": "config", "local": "1"})

    assert cfg.labels["env"] == "1"
    assert cfg.labels["shared"] == "config"
    assert cfg.labels["local"] == "1"
