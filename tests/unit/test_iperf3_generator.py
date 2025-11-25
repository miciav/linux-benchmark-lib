"""Tests for the IPerf3Generator environment checks."""

import ctypes.util

from benchmark_config import IPerf3Config
from workload_generators.iperf3_generator import IPerf3Generator


def test_validate_environment_handles_missing_library(monkeypatch):
    """Generator should fail fast without creating a client when libiperf is missing."""

    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)

    gen = IPerf3Generator(IPerf3Config())
    assert gen._validate_environment() is False  # pylint: disable=protected-access
    assert gen.client is None
