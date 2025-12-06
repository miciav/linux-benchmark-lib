"""Runner-facing benchmark config.

Prefer the legacy linux_benchmark_lib definitions when available (for backwards
compatibility), but fall back to self-contained definitions so remote runner
installs do not depend on the shim package.
"""

from __future__ import annotations

try:
    from linux_benchmark_lib.benchmark_config import *  # type: ignore  # noqa: F401,F403
except ModuleNotFoundError:
    import json
    import logging
    from dataclasses import asdict, dataclass, field
    from pathlib import Path
    from typing import Any, Dict, List, Optional

    _HERE = Path(__file__).resolve()
    _DEFAULT_ANSIBLE_ROOT = _HERE.parent / "ansible"
    _ALT_ANSIBLE_ROOT = _HERE.parent.parent / "lb_controller" / "ansible"
    # Prefer the controller-anchored Ansible assets; fall back to a local folder if present.
    if _ALT_ANSIBLE_ROOT.exists():
        ANSIBLE_ROOT = _ALT_ANSIBLE_ROOT
    else:
        ANSIBLE_ROOT = _DEFAULT_ANSIBLE_ROOT
    logger = logging.getLogger(__name__)

    @dataclass
    class PerfConfig:
        """Configuration for perf profiling."""

        events: List[str] = field(
            default_factory=lambda: [
                "cpu-cycles",
                "instructions",
                "cache-references",
                "cache-misses",
                "branches",
                "branch-misses",
            ]
        )
        interval_ms: int = 1000
        pid: Optional[int] = None
        cpu: Optional[int] = None

    @dataclass
    class MetricCollectorConfig:
        """Configuration for metric collectors."""

        psutil_interval: float = 1.0
        cli_commands: List[str] = field(
            default_factory=lambda: [
                "sar -u 1 1",
                "vmstat 1 1",
                "iostat -d 1 1",
                "mpstat 1 1",
                "pidstat -h 1 1",
            ]
        )
        perf_config: PerfConfig = field(default_factory=PerfConfig)
        enable_ebpf: bool = False

    @dataclass
    class RemoteHostConfig:
        """Configuration for a remote benchmark host."""

        name: str = "localhost"
        address: str = "127.0.0.1"
        port: int = 22
        user: str = "root"
        become: bool = True
        become_method: str = "sudo"
        vars: Dict[str, Any] = field(default_factory=dict)

        def ansible_host_line(self) -> str:
            """Render an INI-style inventory line for this host (compat helper)."""
            parts = [
                self.name,
                f"ansible_host={self.address}",
                f"ansible_port={self.port}",
                f"ansible_user={self.user}",
            ]
            if self.become:
                parts.append("ansible_become=true")
            if self.become_method:
                parts.append(f"ansible_become_method={self.become_method}")
            for key, value in self.vars.items():
                val = str(value)
                if " " in val:
                    val = f"\"{val}\""
                parts.append(f"{key}={val}")
            return " ".join(parts)

    @dataclass
    class RemoteExecutionConfig:
        """Configuration for remote execution via Ansible."""

        enabled: bool = False
        inventory_path: Optional[Path] = None
        run_setup: bool = True
        run_collect: bool = True
        setup_playbook: Path = field(default_factory=lambda: ANSIBLE_ROOT / "playbooks" / "setup.yml")
        run_playbook: Path = field(default_factory=lambda: ANSIBLE_ROOT / "playbooks" / "run_benchmark.yml")
        collect_playbook: Path = field(default_factory=lambda: ANSIBLE_ROOT / "playbooks" / "collect.yml")
        teardown_playbook: Path = field(default_factory=lambda: ANSIBLE_ROOT / "playbooks" / "teardown.yml")
        run_teardown: bool = True
        use_container_fallback: bool = False

    @dataclass
    class WorkloadConfig:
        """Configuration wrapper for workload plugins."""

        plugin: str
        enabled: bool = True
        intensity: str = "user_defined"  # low, medium, high, user_defined
        options: Dict[str, Any] = field(default_factory=dict)

    @dataclass
    class BenchmarkConfig:
        """Main configuration for benchmark tests."""

        # Test execution parameters
        repetitions: int = 3
        test_duration_seconds: int = 3600
        metrics_interval_seconds: float = 1.0
        warmup_seconds: int = 5
        cooldown_seconds: int = 5

        # Output configuration
        output_dir: Path = Path("./benchmark_results")
        report_dir: Path = Path("./reports")
        data_export_dir: Path = Path("./data_exports")

        # Dynamic Plugin Settings (The new way)
        # Stores config objects for migrated plugins (stress_ng, geekbench)
        plugin_settings: Dict[str, Any] = field(default_factory=dict)

        # Metric collector configuration
        collectors: MetricCollectorConfig = field(default_factory=MetricCollectorConfig)

        # Workload plugin configuration (name -> config)
        workloads: Dict[str, WorkloadConfig] = field(default_factory=dict)

        # Remote execution configuration
        remote_hosts: List[RemoteHostConfig] = field(default_factory=list)
        remote_execution: RemoteExecutionConfig = field(default_factory=RemoteExecutionConfig)

        # System information collection
        collect_system_info: bool = True

        # InfluxDB configuration (optional)
        influxdb_enabled: bool = False
        influxdb_url: str = "http://localhost:8086"
        influxdb_token: str = ""
        influxdb_org: str = "benchmark"
        influxdb_bucket: str = "performance"

        def __post_init__(self) -> None:
            self._hydrate_plugin_settings()
            if not self.plugin_settings:
                self._populate_default_plugin_settings()
            self._ensure_workloads_from_plugin_settings()
            self._validate_remote_hosts()

        def ensure_output_dirs(self) -> None:
            for path in (self.output_dir, self.report_dir, self.data_export_dir):
                path.mkdir(parents=True, exist_ok=True)

        def to_json(self) -> str:
            return json.dumps(self.to_dict(), indent=2)

        def to_dict(self) -> Dict[str, Any]:
            def _convert(obj: Any) -> Any:
                if hasattr(obj, "__dict__"):
                    return {k: _convert(v) for k, v in obj.__dict__.items()}
                elif isinstance(obj, Path):
                    return str(obj)
                elif isinstance(obj, dict):
                    return {k: _convert(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [_convert(item) for item in obj]
                else:
                    return obj

            return _convert(self)

        def _validate_remote_hosts(self) -> None:
            if not self.remote_hosts:
                return
            for host in self.remote_hosts:
                if not host.name or not host.name.strip():
                    raise ValueError("remote_hosts names must be non-empty")
            names = [h.name.strip() for h in self.remote_hosts]
            if len(names) != len(set(names)):
                raise ValueError("remote_hosts names must be unique")

        @classmethod
        def from_json(cls, json_str: str) -> "BenchmarkConfig":
            data = json.loads(json_str)
            return cls.from_dict(data)

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkConfig":
            plugin_settings = data.pop("plugin_settings", {})

            # Normalize path-like entries for known plugins
            if "fio" in plugin_settings and isinstance(plugin_settings["fio"], dict):
                if "job_file" in plugin_settings["fio"] and isinstance(plugin_settings["fio"]["job_file"], str):
                    plugin_settings["fio"]["job_file"] = Path(plugin_settings["fio"]["job_file"])

            if "collectors" in data:
                if "perf_config" in data["collectors"]:
                    data["collectors"]["perf_config"] = PerfConfig(**data["collectors"]["perf_config"])
                data["collectors"] = MetricCollectorConfig(**data["collectors"])

            if "remote_hosts" in data:
                data["remote_hosts"] = [RemoteHostConfig(**h) for h in data["remote_hosts"]]

            if "remote_execution" in data:
                # Path conversion logic...
                remote_exec = data["remote_execution"]
                if "inventory_path" in remote_exec and isinstance(remote_exec["inventory_path"], str):
                    remote_exec["inventory_path"] = Path(remote_exec["inventory_path"])
                for key in ["setup_playbook", "run_playbook", "collect_playbook", "teardown_playbook"]:
                    if key in remote_exec and isinstance(remote_exec[key], str):
                        remote_exec[key] = Path(remote_exec[key])
                data["remote_execution"] = RemoteExecutionConfig(**remote_exec)

            for key in ["output_dir", "report_dir", "data_export_dir"]:
                if key in data and isinstance(data[key], str):
                    data[key] = Path(data[key])

            if "workloads" in data:
                data["workloads"] = {
                    name: WorkloadConfig(
                        plugin=cfg.get("plugin", name),
                        enabled=cfg.get("enabled", True),
                        intensity=cfg.get("intensity", "user_defined"),
                        options=cfg.get("options", {}),
                    )
                    for name, cfg in data["workloads"].items()
                }

            data["plugin_settings"] = plugin_settings
            return cls(**data)

        def save(self, filepath: Path) -> None:
            with open(filepath, "w") as f:
                f.write(self.to_json())

        @classmethod
        def load(cls, filepath: Path) -> "BenchmarkConfig":
            with open(filepath, "r") as f:
                data = f.read()
            return cls.from_json(data)

        def _hydrate_plugin_settings(self) -> None:
            """Convert plugin_settings dicts into their respective dataclasses, if necessary."""
            try:
                from lb_runner.plugins.dd.plugin import DDConfig
            except Exception:
                DDConfig = None  # type: ignore
            try:
                from lb_runner.plugins.stress_ng.plugin import StressNGConfig
            except Exception:
                StressNGConfig = None  # type: ignore
            try:
                from lb_runner.plugins.fio.plugin import FIOConfig
            except Exception:
                FIOConfig = None  # type: ignore

            for name, settings in list(self.plugin_settings.items()):
                if name == "dd" and isinstance(settings, dict) and DDConfig:
                    self.plugin_settings[name] = DDConfig(**settings)
                elif name == "stress_ng" and isinstance(settings, dict) and StressNGConfig:
                    self.plugin_settings[name] = StressNGConfig(**settings)
                elif name == "fio" and isinstance(settings, dict) and FIOConfig:
                    self.plugin_settings[name] = FIOConfig(**settings)

        def _ensure_workloads_from_plugin_settings(self) -> None:
            """Populate workloads dict from plugin_settings if not explicitly defined."""
            if not self.plugin_settings:
                return
            for name, settings in self.plugin_settings.items():
                if name not in self.workloads:
                    self.workloads[name] = WorkloadConfig(plugin=name, options=asdict(settings))
                else:
                    # Merge options from plugin_settings into workload config
                    cfg = self.workloads[name]
                    if not cfg.options:
                        cfg.options = asdict(settings)

        def _populate_default_plugin_settings(self) -> None:
            """Fallback default plugin configs (stress_ng only)."""
            try:
                from lb_runner.plugins.stress_ng.plugin import StressNGConfig
            except Exception:
                StressNGConfig = None  # type: ignore
            if StressNGConfig and "stress_ng" not in self.plugin_settings:
                self.plugin_settings["stress_ng"] = StressNGConfig()
