"""Tests for controller run state builders."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lb_plugins.api import PluginAssetConfig
from lb_controller.engine.run_state_builders import (
    ExtravarsBuilder,
    RunDirectoryPreparer,
    build_inventory,
    resolve_run_id,
)
from lb_controller.models.types import InventorySpec
from lb_runner.api import BenchmarkConfig, RemoteHostConfig, WorkloadConfig


pytestmark = pytest.mark.unit_controller


def test_resolve_run_id_prefers_journal() -> None:
    journal = SimpleNamespace(run_id="journal-run")

    assert resolve_run_id("explicit", journal) == "journal-run"


def test_resolve_run_id_uses_explicit_when_no_journal() -> None:
    assert resolve_run_id("explicit", None) == "explicit"


def test_build_inventory_uses_config_hosts(tmp_path) -> None:
    cfg = BenchmarkConfig(output_dir=tmp_path / "out")
    cfg.remote_hosts = [
        RemoteHostConfig(name="host1", address="127.0.0.1", user="root")
    ]

    inventory = build_inventory(cfg)

    assert isinstance(inventory, InventorySpec)
    assert inventory.hosts == cfg.remote_hosts


def test_directory_preparer_creates_per_host_dirs(tmp_path) -> None:
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
    )
    cfg.remote_hosts = [
        RemoteHostConfig(name="host1", address="127.0.0.1", user="root")
    ]
    preparer = RunDirectoryPreparer(cfg)

    output_root, report_root, data_export_root, per_host_output = preparer.prepare(
        "run-1"
    )

    assert output_root.exists()
    assert not report_root.exists()
    assert not data_export_root.exists()
    assert "host1" in per_host_output


def test_extravars_builder_sorts_packages(tmp_path) -> None:
    cfg = BenchmarkConfig(output_dir=tmp_path / "out")
    cfg.remote_hosts = [
        RemoteHostConfig(name="host1", address="127.0.0.1", user="root")
    ]
    builder = ExtravarsBuilder(cfg)
    per_host_output = {"host1": tmp_path / "out" / "host1"}

    extravars = builder.build(
        run_id="run-1",
        output_root=tmp_path / "out",
        report_root=tmp_path / "rep",
        data_export_root=tmp_path / "exp",
        per_host_output=per_host_output,
        target_reps=2,
        collector_packages=["zlib", "apt"],
    )

    assert extravars["run_id"] == "run-1"
    assert extravars["collector_apt_packages"] == ["apt", "zlib"]
    assert extravars["per_host_output"]["host1"].endswith("host1")


def test_extravars_builder_collects_uv_extras_for_enabled_workloads(tmp_path) -> None:
    cfg = BenchmarkConfig(output_dir=tmp_path / "out")
    cfg.workloads = {
        "w1": WorkloadConfig(plugin="peva_faas", enabled=True),
        "w2": WorkloadConfig(plugin="other", enabled=True),
        "w3": WorkloadConfig(plugin="disabled", enabled=False),
    }
    cfg.plugin_assets = {
        "peva_faas": PluginAssetConfig(required_uv_extras=["peva_faas"]),
        "other": PluginAssetConfig(required_uv_extras=["other", "peva_faas"]),
        "disabled": PluginAssetConfig(required_uv_extras=["disabled"]),
    }
    builder = ExtravarsBuilder(cfg)

    extravars = builder.build(
        run_id="run-1",
        output_root=tmp_path / "out",
        report_root=tmp_path / "rep",
        data_export_root=tmp_path / "exp",
        per_host_output={},
        target_reps=1,
        collector_packages=[],
    )

    assert extravars["lb_uv_extras"] == ["other", "peva_faas"]
