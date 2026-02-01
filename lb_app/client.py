"""Application-level client implementation used by UI layers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from lb_app.interfaces import UIHooks, RunRequest
from lb_app.services.config_service import ConfigService
from lb_app.services.provision_service import (
    ProvisionConfigSummary,
    ProvisionService,
    ProvisionStatus,
)
from lb_controller.api import (
    BenchmarkConfig,
    ConnectivityService,
    RemoteHostConfig,
    RunJournal,
    WorkloadConfig,
)
from lb_app.services.run_service import RunService
from lb_app.services.run_service import RunResult
from lb_common.api import RemoteHostSpec, configure_logging
from lb_provisioner.api import (
    ProvisioningService,
    ProvisioningMode,
    ProvisioningRequest,
    ProvisioningError,
)
from lb_plugins.api import create_registry


class ApplicationClient:
    """Concrete application-layer client."""

    def __init__(self) -> None:
        configure_logging()
        self._config_service = ConfigService()
        self._run_service = RunService(registry_factory=create_registry)
        self._provision_service = ProvisionService(self._config_service)
        self._provisioner = ProvisioningService(
            enforce_ui_caller=True, allowed_callers=("lb_ui", "lb_app")
        )

    def load_config(self, path: Path | None = None) -> BenchmarkConfig:
        cfg, _, _ = self._config_service.load_for_read(path)
        return cfg

    def save_config(self, config: BenchmarkConfig, path: Path) -> None:
        config.save(path)
        self._config_service.write_saved_config_path(path)

    def list_runs(self, config: BenchmarkConfig) -> Iterable[RunJournal]:
        return RunJournal.list_runs(config.output_dir)

    def get_run_plan(self, config: BenchmarkConfig, tests: Sequence[str], execution_mode: str = "remote"):
        platform_cfg, _, _ = self._config_service.load_platform_config()
        return self._run_service.get_run_plan(
            config,
            list(tests),
            execution_mode=execution_mode,
            platform_config=platform_cfg,
        )

    def _provision(
        self,
        config: BenchmarkConfig,
        execution_mode: str,
        node_count: int,
        *,
        docker_engine: str | None = None,
        resume: str | None = None,
    ):
        """Provision nodes according to execution mode; returns updated config and provisioner result."""
        mode = ProvisioningMode(execution_mode)
        node_names = None
        if resume and mode in (ProvisioningMode.DOCKER, ProvisioningMode.MULTIPASS):
            node_names = self._resume_node_names(config, resume)
            if not node_names:
                raise ProvisioningError(
                    "Unable to determine previous container/VM names for resume; "
                    "ensure the run journal or host directories are available."
                )
            if node_count != len(node_names):
                raise ProvisioningError(
                    "Resume node count does not match original run; "
                    "use --nodes to match the previous run."
                )
        if mode is ProvisioningMode.REMOTE:
            request = ProvisioningRequest(
                mode=ProvisioningMode.REMOTE,
                count=len(config.remote_hosts),
                remote_hosts=[RemoteHostSpec.from_object(h) for h in config.remote_hosts],
            )
        elif mode is ProvisioningMode.DOCKER:
            request = ProvisioningRequest(
                mode=ProvisioningMode.DOCKER,
                count=node_count,
                node_names=node_names,
                docker_engine=docker_engine or "docker",
            )
        else:
            temp_dir = config.output_dir.parent / "temp_keys"
            request = ProvisioningRequest(
                mode=ProvisioningMode.MULTIPASS,
                count=node_count,
                node_names=node_names,
                state_dir=temp_dir,
            )
        result = self._provisioner.provision(request)
        config.remote_hosts = [
            RemoteHostConfig(
                name=node.host.name,
                address=node.host.address,
                port=node.host.port,
                user=node.host.user,
                become=node.host.become,
                become_method=node.host.become_method,
                vars=node.host.vars,
            )
            for node in result.nodes
        ]
        config.remote_execution.enabled = True
        return config, result

    @staticmethod
    def _resume_node_names(config: BenchmarkConfig, resume: str) -> list[str] | None:
        from lb_app.services.run_journal import (
            find_latest_journal,
            find_latest_results_run,
        )

        run_root = None
        journal_path = None
        if resume == "latest":
            journal_path = find_latest_journal(config)
            if journal_path is not None:
                run_root = journal_path.parent
            else:
                latest = find_latest_results_run(config)
                if latest:
                    journal_path = latest[1]
                    run_root = journal_path.parent
        else:
            run_root = config.output_dir / resume
            journal_path = run_root / "run_journal.json"

        if journal_path is not None and journal_path.exists():
            try:
                journal = RunJournal.load(journal_path)
            except Exception:
                journal = None
            if journal is not None:
                names = sorted(
                    {task.host for task in journal.tasks.values() if task.host}
                )
                if names:
                    return names

        if run_root is not None and run_root.exists():
            names = sorted(
                entry.name
                for entry in run_root.iterdir()
                if entry.is_dir() and not entry.name.startswith("_")
            )
            return names or None
        return None

    def start_run(self, request: RunRequest, hooks: UIHooks) -> RunResult | None:
        cfg = request.config
        target_tests = list(
            request.tests or list(cfg.workloads.keys())
        )
        for name in target_tests:
            if name not in cfg.workloads:
                cfg.workloads[name] = WorkloadConfig(plugin=name, options={})

        context = self._run_service.create_session(
            self._config_service,
            tests=target_tests,
            config_path=None,
            run_id=request.run_id,
            resume=request.resume,
            repetitions=request.repetitions,
            debug=request.debug,
            intensity=request.intensity,
            ui_adapter=request.ui_adapter,
            setup=request.setup,
            stop_file=request.stop_file,
            execution_mode=request.execution_mode,
            node_count=request.node_count,
            preloaded_config=cfg,
        )

        # Pre-flight connectivity check for remote mode
        if (
            not request.skip_connectivity_check
            and request.execution_mode == "remote"
            and cfg.remote_hosts
        ):
            connectivity_service = ConnectivityService(
                timeout_seconds=request.connectivity_timeout
            )
            connectivity_report = connectivity_service.check_hosts(cfg.remote_hosts)
            if not connectivity_report.all_reachable:
                unreachable = ", ".join(connectivity_report.unreachable_hosts)
                hooks.on_warning(
                    f"Unreachable hosts: {unreachable}. "
                    "Use --skip-connectivity-check to bypass this check.",
                    ttl=10,
                )
                return None

        # Provision according to execution mode
        prov_result = None
        try:
            cfg, prov_result = self._provision(
                cfg,
                request.execution_mode,
                request.node_count,
                docker_engine=request.docker_engine,
                resume=request.resume,
            )
        except ProvisioningError as exc:
            hooks.on_warning(f"Provisioning failed: {exc}", ttl=5)
            return None
        context.config = cfg

        run_result: RunResult | None = None
        try:
            output_cb = None
            # If no UI adapter is provided, forward raw logs to hooks.
            if request.ui_adapter is None:
                def _output_cb(text: str, end: str = "") -> None:
                    hooks.on_log(text)

                output_cb = _output_cb

            run_result = self._run_service.execute(
                context,
                run_id=request.run_id,
                output_callback=output_cb,
                ui_adapter=request.ui_adapter,
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

    def install_loki_grafana(
        self,
        *,
        mode: str,
        config_path: Path | None,
        grafana_url: str | None,
        grafana_api_key: str | None,
        grafana_admin_user: str | None,
        grafana_admin_password: str | None,
        grafana_token_name: str | None,
        grafana_org_id: int | None,
        loki_endpoint: str | None,
        configure_assets: bool = True,
    ) -> ProvisionConfigSummary | None:
        return self._provision_service.install_loki_grafana(
            mode=mode,
            config_path=config_path,
            grafana_url=grafana_url,
            grafana_api_key=grafana_api_key,
            grafana_admin_user=grafana_admin_user,
            grafana_admin_password=grafana_admin_password,
            grafana_token_name=grafana_token_name,
            grafana_org_id=grafana_org_id,
            loki_endpoint=loki_endpoint,
            configure_assets=configure_assets,
        )

    def remove_loki_grafana(self, *, remove_data: bool = False) -> None:
        self._provision_service.remove_loki_grafana(remove_data=remove_data)

    def status_loki_grafana(
        self,
        *,
        grafana_url: str | None,
        grafana_api_key: str | None,
        grafana_org_id: int | None,
        loki_endpoint: str | None,
    ) -> ProvisionStatus:
        return self._provision_service.status_loki_grafana(
            grafana_url=grafana_url,
            grafana_api_key=grafana_api_key,
            grafana_org_id=grafana_org_id,
            loki_endpoint=loki_endpoint,
        )
