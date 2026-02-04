"""
Phoronix Test Suite (PTS) workload bundle.

This module exposes multiple `WorkloadPlugin` instances, one per configured PTS
test-profile or test-suite. New profiles can be added by editing `pts_workloads.yaml`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import yaml
from pydantic import Field, model_validator

from ...base_generator import CommandGenerator
from ...interface import BasePluginConfig, WorkloadPlugin
from ...utils.csv_export import write_csv_rows

logger = logging.getLogger(__name__)


def _derive_plugin_name(profile: str) -> str:
    safe = profile.strip().lower().replace("-", "_").replace(" ", "_")
    safe = "".join(ch for ch in safe if ch.isalnum() or ch == "_").strip("_")
    return f"pts_{safe}" if safe else "pts_unknown"

def _ensure_trailing_sep(path_value: str) -> str:
    stripped = path_value.strip()
    if not stripped:
        return stripped
    expanded = os.path.expanduser(stripped)
    return expanded if expanded.endswith(os.sep) else expanded + os.sep


def _looks_like_menu_prompt(line: str) -> bool:
    lower = line.lower()
    if "multiple items can be selected" in lower:
        return True
    if "test configuration" in lower and ("1:" in line or "2:" in line):
        return True
    return False


@dataclass(frozen=True)
class PtsDefaults:
    """Resolved defaults from the YAML file."""

    binary: str
    deb_relpath: str
    apt_packages: List[str]
    # PTS_USER_PATH_OVERRIDE (directory with trailing slash).
    home_root: str


@dataclass(frozen=True)
class PtsWorkloadSpec:
    """A single configured PTS workload profile."""

    profile: str
    plugin_name: str
    description: str
    tags: List[str]
    args: List[str]
    apt_packages: List[str]
    expected_runtime_seconds: Optional[int]


class _PtsManifestParser:
    """Parse PTS workload manifest YAML into defaults and workload specs."""

    def parse(self, path: Path) -> tuple[PtsDefaults, List[PtsWorkloadSpec]]:
        data = self._load_yaml(path)
        defaults = self._parse_defaults(data)
        specs = self._parse_workloads(data)
        self._validate_unique_names(specs)
        return defaults, specs

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError("PTS config must be a YAML mapping")
        return data

    @staticmethod
    def _parse_defaults(data: dict[str, Any]) -> PtsDefaults:
        pts_data = data.get("pts") or {}
        if not isinstance(pts_data, dict):
            raise ValueError("pts section must be a mapping")

        binary = str(pts_data.get("binary") or "phoronix-test-suite")
        deb_relpath = str(pts_data.get("deb_path") or "").strip()
        if not deb_relpath:
            raise ValueError("pts.deb_path is required")
        apt_packages = _PtsManifestParser._require_string_list(
            pts_data.get("apt_packages") or [],
            "pts.apt_packages must be a list of strings",
        )
        home_root = str(
            pts_data.get("home_root") or "~/.lb/.phoronix-test-suite/"
        ).strip()
        return PtsDefaults(
            binary=binary,
            deb_relpath=deb_relpath,
            apt_packages=apt_packages,
            home_root=_ensure_trailing_sep(home_root),
        )

    def _parse_workloads(self, data: dict[str, Any]) -> List[PtsWorkloadSpec]:
        raw_workloads = data.get("workloads") or []
        if not isinstance(raw_workloads, list):
            raise ValueError("workloads must be a list")
        specs: List[PtsWorkloadSpec] = []
        for item in raw_workloads:
            specs.append(self._parse_workload_entry(item))
        return specs

    def _parse_workload_entry(self, item: Any) -> PtsWorkloadSpec:
        if isinstance(item, str):
            profile = item.strip()
            plugin_name = _derive_plugin_name(profile)
            return PtsWorkloadSpec(
                profile=profile,
                plugin_name=plugin_name,
                description=f"PTS profile: {profile}",
                tags=["pts"],
                args=[],
                apt_packages=[],
                expected_runtime_seconds=None,
            )
        if isinstance(item, dict):
            return self._parse_workload_mapping(item)
        raise ValueError("workloads entries must be strings or mappings")

    def _parse_workload_mapping(self, item: dict[str, Any]) -> PtsWorkloadSpec:
        profile = str(item.get("profile") or "").strip()
        if not profile:
            raise ValueError("workloads entry missing 'profile'")
        plugin_name = str(
            item.get("plugin_name") or _derive_plugin_name(profile)
        ).strip()
        description = str(item.get("description") or f"PTS profile: {profile}").strip()
        tags = self._require_string_list(
            item.get("tags") or ["pts"],
            f"workload {profile}: tags must be a list of strings",
        )
        args = self._require_string_list(
            item.get("args") or [],
            f"workload {profile}: args must be a list of strings",
        )
        apt_packages = self._require_string_list(
            item.get("apt_packages") or [],
            f"workload {profile}: apt_packages must be a list of strings",
        )
        expected_runtime_seconds = item.get("expected_runtime_seconds")
        if expected_runtime_seconds is not None and not isinstance(
            expected_runtime_seconds, int
        ):
            raise ValueError(
                f"workload {profile}: expected_runtime_seconds must be int"
            )
        return PtsWorkloadSpec(
            profile=profile,
            plugin_name=plugin_name,
            description=description,
            tags=tags,
            args=args,
            apt_packages=apt_packages,
            expected_runtime_seconds=expected_runtime_seconds,
        )

    @staticmethod
    def _require_string_list(value: Any, error: str) -> List[str]:
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError(error)
        return list(value)

    @staticmethod
    def _validate_unique_names(specs: List[PtsWorkloadSpec]) -> None:
        names = [spec.plugin_name for spec in specs]
        dupes = {name for name in names if names.count(name) > 1}
        if dupes:
            raise ValueError(
                f"Duplicate plugin_name(s) in PTS config: {sorted(dupes)}"
            )


class PhoronixConfig(BasePluginConfig):
    """Common configuration for PTS workloads."""

    batch_mode: bool = Field(
        default=True,
        description=(
            "Batch mode is required for PTS workloads (non-batch is unsupported)."
        ),
    )
    install_system_packages: bool = Field(
        default=True,
        description=(
            "Deprecated for execution: installs run in the setup phase, "
            "not during workload runs."
        ),
    )
    timeout_seconds: int = Field(
        default=0,
        ge=0,
        description="Hard timeout for the PTS command; 0 disables.",
    )
    extra_args: List[str] = Field(
        default_factory=list,
        description="Additional arguments appended to the PTS command.",
    )

    @model_validator(mode="after")
    def _require_batch_mode(self) -> "PhoronixConfig":
        if not self.batch_mode:
            raise ValueError("PTS workloads require batch mode (batch_mode=True).")
        return self


class PtsResultParser:
    """Parse PTS command output and resolve result directories."""

    def __init__(self, profile: str) -> None:
        self._profile = profile

    @staticmethod
    def snapshot_results(results_root: Path) -> set[str]:
        if not results_root.exists():
            return set()
        try:
            return {p.name for p in results_root.iterdir() if p.is_dir()}
        except Exception:
            return set()

    @staticmethod
    def select_result_dir(
        results_root: Path, before: set[str]
    ) -> tuple[str | None, str | None]:
        try:
            candidates = [p for p in results_root.iterdir() if p.is_dir()]
            new_dirs = [p for p in candidates if p.name not in before]
            picked = None
            if new_dirs:
                picked = max(new_dirs, key=lambda p: p.stat().st_mtime)
            elif candidates:
                picked = max(candidates, key=lambda p: p.stat().st_mtime)
            if picked:
                return str(picked.resolve()), picked.name
        except Exception:
            pass
        return None, None

    @staticmethod
    def normalize_returncode(rc: int, output: str) -> int:
        output_lower = output.lower()
        failure_markers = (
            "[problem]",
            "the batch mode must first be configured",
            "unable to locate package",
            "has no installation candidate",
            "the update command takes no arguments",
        )
        if rc == 0 and any(marker in output_lower for marker in failure_markers):
            return 2
        return rc

    def build_success_result(
        self,
        cmd: List[str],
        rc: int,
        output: str,
        pts_result_dir: str | None,
        pts_result_id: str | None,
        start: float,
    ) -> dict[str, Any]:
        return {
            "command": " ".join(cmd),
            "profile": self._profile,
            "returncode": rc,
            "stdout": output,
            "pts_result_dir": pts_result_dir,
            "pts_result_id": pts_result_id,
            "duration_seconds": self._duration_seconds(start),
        }

    def build_error_result(
        self,
        cmd: List[str],
        error_type: str,
        message: str,
        start: float,
    ) -> dict[str, Any]:
        return {
            "command": " ".join(cmd),
            "profile": self._profile,
            "returncode": -1 if error_type == "timeout" else -2,
            "error": message,
            "duration_seconds": self._duration_seconds(start),
        }

    @staticmethod
    def _duration_seconds(start: float) -> float:
        return round(time.time() - start, 3)


class PhoronixGenerator(CommandGenerator):
    """Workload generator that runs a single PTS test-profile or test-suite."""

    def __init__(
        self,
        *,
        config: PhoronixConfig,
        binary: str,
        profile: str,
        home_root: str,
        profile_args: List[str],
        system_packages: List[str],
        expected_runtime_seconds: Optional[int],
        name: str,
    ):
        super().__init__(name, config)
        self.binary = binary
        self.profile = profile
        self.home_root = home_root
        self.profile_args = profile_args
        self.system_packages = system_packages
        self.expected_runtime_seconds = expected_runtime_seconds
        self._result_parser = PtsResultParser(self.profile)

    def _validate_environment(self) -> bool:
        return shutil.which(self.binary) is not None

    def _batch_config_paths(self, pts_user_path: str) -> List[Path]:
        # If running as root and /etc is writable, PTS stores config globally.
        # Otherwise it stores per-user under PTS_USER_PATH.
        candidates = [
            Path("/etc/phoronix-test-suite.xml"),
            Path(pts_user_path) / "user-config.xml",
        ]
        return candidates

    def _is_batch_configured(self, pts_user_path: str) -> bool:
        for candidate in self._batch_config_paths(pts_user_path):
            if not candidate.exists():
                continue
            try:
                content = candidate.read_text(errors="ignore").lower()
            except Exception:
                continue
            if "<configured>true</configured>" in content:
                return True
        return False

    def _require_batch_setup(self, env: Dict[str, str]) -> None:
        pts_user_path = env.get("PTS_USER_PATH_OVERRIDE", "")
        if not pts_user_path:
            return
        if self._is_batch_configured(pts_user_path):
            return
        raise RuntimeError(
            "PTS batch mode is not configured. Run the plugin setup phase or "
            "`phoronix-test-suite batch-setup` before executing workloads."
        )

    def _is_profile_installed(self, env: Dict[str, str]) -> bool:
        pts_user_path = env.get("PTS_USER_PATH_OVERRIDE", "")
        if pts_user_path:
            base = Path(pts_user_path)
            candidates = [
                base / "test-profiles" / "pts" / self.profile / "test-definition.xml",
                base / "test-profiles" / self.profile / "test-definition.xml",
                base / "test-suites" / "pts" / self.profile / "suite-definition.xml",
                base / "test-suites" / self.profile / "suite-definition.xml",
            ]
            if any(path.exists() for path in candidates):
                return True
        profile = self.profile.strip().lower()
        for subcommand in ("list-installed-tests", "list-installed-suites"):
            try:
                res = subprocess.run(
                    [self.binary, subcommand],
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            except Exception:
                continue
            if res.returncode != 0:
                continue
            for line in (res.stdout or "").splitlines():
                if profile and profile in line.lower():
                    return True
        return False

    def _check_system_packages(self, env: Dict[str, str]) -> None:
        if not self.system_packages:
            return
        if shutil.which("dpkg-query") is None:
            return
        missing: list[str] = []
        for pkg in sorted(set(self.system_packages)):
            res = subprocess.run(
                ["dpkg-query", "-W", "-f=${Status}", pkg],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if res.returncode != 0 or "install ok installed" not in (res.stdout or ""):
                missing.append(pkg)
        if missing:
            raise RuntimeError(
                "Missing system packages for PTS profile "
                f"'{self.profile}': {', '.join(missing)}. "
                "Run the plugin setup phase before executing workloads."
            )

    def prepare(self) -> None:
        """
        Validate that setup ran before workload execution.

        Installations must happen in the setup phase, not during workload runs.
        """
        env, _ = self._prepare_env()
        self._ensure_profile_ready(env)

    def _prepare_env(self) -> tuple[dict[str, str], Path]:
        pts_user_path = Path(_ensure_trailing_sep(self.home_root))
        pts_user_path.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PTS_USER_PATH_OVERRIDE"] = str(pts_user_path)
        return env, pts_user_path

    def _ensure_profile_ready(self, env: dict[str, str]) -> None:
        if not self._validate_environment():
            raise RuntimeError(f"Missing required tool: {self.binary}")
        self._require_batch_setup(env)
        self._check_system_packages(env)
        if not self._is_profile_installed(env):
            raise RuntimeError(
                f"PTS profile '{self.profile}' is not installed. "
                "Run the plugin setup phase before executing workloads."
            )

    def _build_command_for(self, subcommand: str) -> List[str]:
        cmd = [self.binary, subcommand, self.profile]
        cmd.extend(self.profile_args)
        cmd.extend(self.config.extra_args)
        return cmd

    def _build_command(self) -> List[str]:
        return self._build_command_for("batch-benchmark")

    def _run_command(self) -> None:
        start = time.time()
        cmd = self._build_command_for("batch-benchmark")
        try:
            env, pts_user_path = self._prepare_env()
            self._ensure_profile_ready(env)
            results_root = pts_user_path / "test-results"
            before = self._result_parser.snapshot_results(results_root)
            rc, out = self._run_pts_process(cmd, env, start)
            rc = self._result_parser.normalize_returncode(rc, out)
            pts_result_dir, pts_result_id = self._result_parser.select_result_dir(
                results_root, before
            )
            self._result = self._result_parser.build_success_result(
                cmd, rc, out, pts_result_dir, pts_result_id, start
            )
        except subprocess.TimeoutExpired:
            self._stop_workload()
            self._result = self._result_parser.build_error_result(
                cmd,
                "timeout",
                f"Timeout after {self.config.timeout_seconds}s",
                start,
            )
        except Exception as exc:
            self._result = self._result_parser.build_error_result(
                cmd, "error", str(exc), start
            )
        finally:
            self._process = None
            self._is_running = False

    def _run_pts_process(
        self,
        cmd: List[str],
        env: dict[str, str],
        start: float,
    ) -> tuple[int, str]:
        logger.info("Running PTS command: %s", " ".join(cmd))
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        assert self._process.stdout is not None
        assert self._process.stdin is not None
        output_lines: List[str] = []
        deadline = (
            start + self.config.timeout_seconds
            if self.config.timeout_seconds
            else None
        )
        menu_responses = 0
        while True:
            if deadline and time.time() > deadline:
                raise subprocess.TimeoutExpired(cmd, self.config.timeout_seconds)
            line = self._process.stdout.readline()
            if not line and self._process.poll() is not None:
                break
            if line:
                print(line, end="", flush=True)
                output_lines.append(line)
                if _looks_like_menu_prompt(line) and menu_responses < 3:
                    self._respond_to_menu_prompt(menu_responses)
                    menu_responses += 1
        rc = self._process.wait()
        return rc, "".join(output_lines)

    def _respond_to_menu_prompt(self, attempts: int) -> None:
        if not self._process or not self._process.stdin or attempts >= 3:
            return
        try:
            self._process.stdin.write("1\n")
            self._process.stdin.flush()
        except Exception:
            pass

    def _stop_workload(self) -> None:
        proc = self._process
        if not proc or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                return
        try:
            proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


class PhoronixTestSuiteWorkloadPlugin(WorkloadPlugin):
    """A single PTS test-profile or test-suite exposed as a WorkloadPlugin."""

    def __init__(
        self,
        *,
        spec: PtsWorkloadSpec,
        defaults: PtsDefaults,
        ansible_setup_path: Path,
        ansible_teardown_path: Path,
    ):
        self._spec = spec
        self._defaults = defaults
        self._ansible_setup_path = ansible_setup_path
        self._ansible_teardown_path = ansible_teardown_path

    @property
    def name(self) -> str:
        return self._spec.plugin_name

    @property
    def description(self) -> str:
        return self._spec.description

    @property
    def config_cls(self) -> Type[BasePluginConfig]:
        return PhoronixConfig

    def create_generator(self, config: BasePluginConfig) -> Any:
        if not isinstance(config, PhoronixConfig):
            cfg = PhoronixConfig.model_validate(
                config.model_dump() if hasattr(config, "model_dump") else config
            )
        else:
            cfg = config
        combined_packages = sorted(
            set(self._defaults.apt_packages + self._spec.apt_packages)
        )
        return PhoronixGenerator(
            config=cfg,
            binary=self._defaults.binary,
            profile=self._spec.profile,
            home_root=self._defaults.home_root,
            profile_args=self._spec.args,
            system_packages=combined_packages,
            expected_runtime_seconds=self._spec.expected_runtime_seconds,
            name=f"PTS[{self._spec.profile}]",
        )

    def get_required_local_tools(self) -> List[str]:
        return [self._defaults.binary]

    def get_ansible_setup_path(self) -> Optional[Path]:
        return self._ansible_setup_path

    def get_ansible_setup_extravars(self) -> Dict[str, Any]:
        combined = sorted(set(self._defaults.apt_packages + self._spec.apt_packages))
        return {
            "pts_profile": self._spec.profile,
            "pts_deb_relpath": self._defaults.deb_relpath,
            "pts_home_root": self._defaults.home_root,
            "pts_apt_packages": combined,
        }

    def get_ansible_teardown_path(self) -> Optional[Path]:
        return self._ansible_teardown_path

    def get_ansible_teardown_extravars(self) -> Dict[str, Any]:
        return self.get_ansible_setup_extravars()

    def export_results_to_csv(
        self,
        results: List[Dict[str, Any]],
        output_dir: Path,
        run_id: str,
        test_name: str,
    ) -> List[Path]:
        for entry in results:
            gen_result = entry.get("generator_result") or {}
            rep = entry.get("repetition")
            if not isinstance(rep, int) or rep <= 0:
                continue
            src = gen_result.get("pts_result_dir")
            if not isinstance(src, str) or not src:
                continue
            src_path = Path(src)
            if not src_path.exists() or not src_path.is_dir():
                continue
            dest = output_dir / "pts_results" / f"rep{rep}" / src_path.name
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src_path, dest, dirs_exist_ok=True)
            except Exception as exc:  # pragma: no cover - best effort artifact copy
                logger.debug(
                    "Failed to copy PTS results from %s to %s: %s",
                    src_path,
                    dest,
                    exc,
                )

        rows: list[dict[str, Any]] = []
        for entry in results:
            gen_result = entry.get("generator_result") or {}
            rows.append(
                {
                    "run_id": run_id,
                    "workload": test_name,
                    "repetition": entry.get("repetition"),
                    "success": entry.get("success"),
                    "duration_seconds": entry.get("duration_seconds"),
                    "profile": gen_result.get("profile"),
                    "returncode": gen_result.get("returncode"),
                }
            )
        if not rows:
            return []
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{test_name}_pts.csv"
        write_csv_rows(
            rows,
            csv_path,
            [
                "run_id",
                "workload",
                "repetition",
                "success",
                "duration_seconds",
                "profile",
                "returncode",
            ],
        )
        return [csv_path]


def _load_manifest(path: Path) -> tuple[PtsDefaults, List[PtsWorkloadSpec]]:
    parser = _PtsManifestParser()
    return parser.parse(path)


def get_plugins() -> List[WorkloadPlugin]:
    """
    Return virtual PTS workload plugins driven by `pts_workloads.yaml`.

    This is intentionally evaluated at registry creation time so editing the YAML
    is sufficient to add/remove workloads.
    """
    config_path = Path(__file__).with_name("pts_workloads.yaml")
    defaults, specs = _load_manifest(config_path)
    ansible_setup_path = Path(__file__).parent / "ansible" / "setup_plugin.yml"
    ansible_teardown_path = Path(__file__).parent / "ansible" / "teardown.yml"
    plugins: List[WorkloadPlugin] = []
    for spec in specs:
        plugins.append(
            PhoronixTestSuiteWorkloadPlugin(
                spec=spec,
                defaults=defaults,
                ansible_setup_path=ansible_setup_path,
                ansible_teardown_path=ansible_teardown_path,
            )
        )
    logger.debug(
        "PTS plugin bundle created %s workload(s): %s",
        len(plugins),
        json.dumps([p.name for p in plugins]),
    )
    return plugins
