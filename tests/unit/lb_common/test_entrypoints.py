"""Tests for entry-point discovery helpers."""

from __future__ import annotations

import importlib.metadata

import pytest

from lb_common.discovery.entrypoints import discover_entrypoints


pytestmark = pytest.mark.unit_runner


def test_discover_entrypoints_handles_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_error():
        raise RuntimeError("boom")

    monkeypatch.setattr(importlib.metadata, "entry_points", raise_error)

    result = discover_entrypoints(["linux_benchmark.collectors"])
    assert result == {}


def test_discover_entrypoints_collects_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_entry = importlib.metadata.EntryPoint(
        name="demo", value="demo.module:OBJ", group="linux_benchmark.collectors"
    )

    class FakeEntries:
        def select(self, group: str):
            assert group == "linux_benchmark.collectors"
            return [fake_entry]

    monkeypatch.setattr(importlib.metadata, "entry_points", lambda: FakeEntries())

    result = discover_entrypoints(["linux_benchmark.collectors"])
    assert result["demo"] == fake_entry
