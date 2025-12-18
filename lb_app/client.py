"""Application-level client implementation used by UI layers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from lb_app.interfaces import AppClient, UIHooks, RunRequest
from lb_controller.services import ConfigService, RunService
from lb_controller.services.run_service import RunContext
from lb_controller.journal import RunJournal
from lb_controller.services.plugin_service import create_registry
from lb_controller.services.run_service import RunResult
from lb_provisioner import (
    ProvisioningService,
    ProvisioningMode,
    ProvisioningRequest,
    ProvisioningError,
)
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig


class ApplicationClient(AppClient):
    """Concrete application-layer client."""

    def __init__(self) -> None:
        self._config_service = ConfigService()
        self._run_service = RunService(registry_factory=create_registry)
        self._provisioner = ProvisioningService(enforce_ui_caller=False)

    def load_config(self, path: Path | None = None) -> BenchmarkConfig:
        cfg, _, _ = self._config_service.load_for_read(path)
        return cfg

    def save_config(self, config: BenchmarkConfig, path: Path) -> None:
        config.save(path)
        self._config_service.write_saved_config_path(path)

    def list_runs(self, config: BenchmarkConfig) -> Iterable[RunJournal]:
        return RunJournal.list_runs(config.output_dir)

    def get_run_plan(self, config: BenchmarkConfig, tests: Sequence[str], execution_mode: str = "remote"):
        return self._run_service.get_run_plan(config, list(tests), execution_mode=execution_mode)

    def _provision(self, config: BenchmarkConfig, execution_mode: str, node_count: int, docker_engine: str | None = None):
        """Provision nodes according to execution mode; returns updated config and provisioner result."""
        mode = ProvisioningMode(execution_mode)
        if mode is ProvisioningMode.REMOTE:
            request = ProvisioningRequest(
                mode=ProvisioningMode.REMOTE,
                count=len(config.remote_hosts),
                remote_hosts=config.remote_hosts,
            )
        elif mode is ProvisioningMode.DOCKER:
            request = ProvisioningRequest(
                mode=ProvisioningMode.DOCKER,
                count=node_count,
                docker_engine=docker_engine or "docker",
            )
        else:
            temp_dir = config.output_dir.parent / "temp_keys"
            request = ProvisioningRequest(
                mode=ProvisioningMode.MULTIPASS,
                count=node_count,
                state_dir=temp_dir,
            )
        result = self._provisioner.provision(request)
        config.remote_hosts = [node.host for node in result.nodes]
        config.remote_execution.enabled = True
        return config, result

    def start_run(self, request: RunRequest, hooks: UIHooks) -> RunResult | None:
        cfg = request.config
        cfg.ensure_output_dirs()
        target_tests = list(request.tests or [name for name, wl in cfg.workloads.items() if wl.enabled])
        # Make sure workloads exist
        for name in target_tests:
            if name not in cfg.workloads:
                cfg.workloads[name] = WorkloadConfig(plugin=name, enabled=True)

        # Provision according to execution mode
        prov_result = None
        try:
            cfg, prov_result = self._provision(cfg, request.execution_mode, request.node_count, request.docker_engine)
        except ProvisioningError as exc:
            hooks.on_warning(f"Provisioning failed: {exc}", ttl=5)
            return None

        context = RunContext(
            config=cfg,
            target_tests=target_tests,
            registry=create_registry(),
            config_path=None,
            debug=request.debug,
            resume_from=request.resume,
            resume_latest=request.resume == "latest",
            stop_file=request.stop_file,
            execution_mode=request.execution_mode,
        )

        run_result: RunResult | None = None
        try:
            run_result = self._run_service.execute(
                context,
                run_id=request.run_id,
                output_callback=lambda text, end="": hooks.on_log(text),
                ui_adapter=None,
            )
            if run_result.summary and hasattr(run_result.summary, "controller_state"):
                hooks.on_status(str(run_result.summary.controller_state))
        finally:
            if prov_result:
                if run_result and run_result.summary and getattr(run_result.summary, "cleanup_allowed", False):
                    prov_result.destroy_all()
                else:
                    prov_result.keep_nodes = True
                    hooks.on_warning("Leaving provisioned nodes for inspection", ttl=5)
        return run_result
