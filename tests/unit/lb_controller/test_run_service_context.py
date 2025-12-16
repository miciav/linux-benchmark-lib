"""Tests for RunService build_context behavior."""

from pathlib import Path

from lb_controller.services.run_service import RunService
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig
import pytest

pytestmark = pytest.mark.unit

class DummyRegistry:
    pass


def _cfg_with_workload():
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
    return cfg


def test_build_context_respects_remote_override():
    svc = RunService(registry_factory=lambda: DummyRegistry())
    cfg = _cfg_with_workload()
    ctx = svc.build_context(cfg, tests=None, remote_override=True)
    assert ctx.use_remote is True

    cfg.remote_execution.enabled = False
    ctx2 = svc.build_context(cfg, tests=None, remote_override=None)
    assert ctx2.use_remote is False


def test_build_context_sets_multipass_and_counts():
    svc = RunService(registry_factory=lambda: DummyRegistry())
    cfg = _cfg_with_workload()
    ctx = svc.build_context(cfg, tests=None, remote_override=False, multipass=True, multipass_vm_count=3)
    assert ctx.use_multipass is True
    assert ctx.use_remote is True  # multipass implies remote
    assert ctx.multipass_count == 3


def test_build_context_sets_container_flags():
    svc = RunService(registry_factory=lambda: DummyRegistry())
    cfg = _cfg_with_workload()
    ctx = svc.build_context(
        cfg,
        tests=None,
        remote_override=False,
        docker=True,
        docker_image="custom:tag",
        docker_engine="podman",
        docker_build=False,
        docker_no_cache=True,
    )
    assert ctx.use_container is True
    assert ctx.docker_image == "custom:tag"
    assert ctx.docker_engine == "podman"
    assert ctx.docker_build is False
    assert ctx.docker_no_cache is True
    assert ctx.docker_workdir and isinstance(ctx.docker_workdir, Path)
