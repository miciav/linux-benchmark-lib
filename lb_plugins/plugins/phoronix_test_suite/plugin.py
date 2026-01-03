"""
Phoronix Test Suite (PTS) workload bundle.

This module exposes multiple `WorkloadPlugin` instances, one per configured PTS
test-profile. New profiles can be added by editing `pts_workloads.yaml`.
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
from pydantic import Field

from lb_runner.plugin_system.base_generator import BaseGenerator
from lb_runner.plugin_system.interface import BasePluginConfig, WorkloadPlugin

logger = logging.getLogger(__name__)


def _derive_plugin_name(profile: str) -> str:
    safe = profile.strip().lower().replace("-", "_").replace(" ", "_")
    safe = "".join(ch for ch in safe if ch.isalnum() or ch == "_").strip("_")
    return f"pts_{safe}" if safe else "pts_unknown"

def _ensure_trailing_sep(path_value: str) -> str:
    stripped = path_value.strip()
    if not stripped:
        return stripped
    return stripped if stripped.endswith(os.sep) else stripped + os.sep


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


class PhoronixConfig(BasePluginConfig):
    """Common configuration for PTS workloads."""

    batch_mode: bool = Field(
        default=True,
        description="Prefer batch-* PTS commands to avoid interactive prompts.",
    )
    install_system_packages: bool = Field(
        default=True,
        description="When running as root, install required APT packages before executing PTS.",
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


class PhoronixGenerator(BaseGenerator):
    """Workload generator that runs a single PTS test-profile."""

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
        super().__init__(name)
        self.config = config
        self.binary = binary
        self.profile = profile
        self.home_root = home_root
        self.profile_args = profile_args
        self.system_packages = system_packages
        self.expected_runtime_seconds = expected_runtime_seconds
        self._process: Optional[subprocess.Popen[str]] = None

    def _validate_environment(self) -> bool:
        return shutil.which(self.binary) is not None

    def _batch_config_paths(self, pts_user_path: str) -> List[Path]:
        # If running as root and /etc is writable, PTS stores config globally.
        # Otherwise it stores per-user under PTS_USER_PATH.
        candidates = [Path("/etc/phoronix-test-suite.xml"), Path(pts_user_path) / "user-config.xml"]
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

    def _ensure_batch_setup(self, env: Dict[str, str]) -> None:
        pts_user_path = env.get("PTS_USER_PATH_OVERRIDE", "")
        if not pts_user_path:
            return
        if not self.config.batch_mode:
            return
        if self._is_batch_configured(pts_user_path):
            return

        # Configure batch mode explicitly to avoid:
        # - result uploads to OpenBenchmarking.org
        # - interactive prompts for identifiers/descriptions
        # - running all test combinations
        answers = "Y\nN\nN\nN\nN\nN\nN\n"
        res = subprocess.run(
            [self.binary, "batch-setup"],
            env=env,
            text=True,
            input=answers,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"PTS batch-setup failed: {res.stdout}".strip())
        if not self._is_batch_configured(pts_user_path):
            raise RuntimeError(
                "PTS batch mode is still not configured after batch-setup. "
                "Try running `phoronix-test-suite batch-setup` manually."
            )

    def prepare(self) -> None:
        """
        Best-effort profile install before collectors start.

        Container runs execute with `--no-setup`, so we must ensure the PTS profile
        is installed here to avoid interactive prompts during `benchmark`.
        """
        pts_user_path = _ensure_trailing_sep(self.home_root)
        Path(pts_user_path).mkdir(parents=True, exist_ok=True)
        if not self._validate_environment():
            raise RuntimeError(f"Missing required tool: {self.binary}")

        if (
            self.config.install_system_packages
            and os.geteuid() == 0
            and shutil.which("apt-get") is not None
            and self.system_packages
        ):
            env = os.environ.copy()
            env["DEBIAN_FRONTEND"] = "noninteractive"
            env["PTS_USER_PATH_OVERRIDE"] = pts_user_path
            install_cmd = [
                "apt-get",
                "install",
                "-y",
                "--no-install-recommends",
                *sorted(set(self.system_packages)),
            ]
            update_res = subprocess.run(
                ["apt-get", "update"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if update_res.returncode != 0:
                raise RuntimeError(f"APT update failed for PTS deps: {update_res.stdout}".strip())
            res = subprocess.run(
                install_cmd,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if res.returncode != 0:
                raise RuntimeError(f"APT install failed for PTS deps: {res.stdout}".strip())

        env = os.environ.copy()
        env["PTS_USER_PATH_OVERRIDE"] = pts_user_path
        self._ensure_batch_setup(env)

        def _run(cmd: List[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                env=env,
                text=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

        cmds = [
            [self.binary, "batch-install", self.profile, *self.profile_args],
            [self.binary, "install", self.profile, *self.profile_args],
        ]
        last = None
        for cmd in cmds:
            last = _run(cmd)
            if last.returncode == 0:
                return
        out = (last.stdout if last else "") or ""
        raise RuntimeError(f"PTS profile install failed for '{self.profile}': {out}".strip())

    def _build_command(self, subcommand: str) -> List[str]:
        cmd = [self.binary, subcommand, self.profile]
        cmd.extend(self.profile_args)
        cmd.extend(self.config.extra_args)
        return cmd

    def _run_command(self) -> None:
        start = time.time()
        env = os.environ.copy()
        pts_user_path = _ensure_trailing_sep(self.home_root)
        env["PTS_USER_PATH_OVERRIDE"] = pts_user_path
        # Ensure batch mode is configured even if `prepare()` was skipped.
        self._ensure_batch_setup(env)
        results_root = Path(pts_user_path) / "test-results"
        before: set[str] = set()
        try:
            if results_root.exists():
                before = {p.name for p in results_root.iterdir() if p.is_dir()}
        except Exception:
            before = set()

        cmd = self._build_command("batch-benchmark" if self.config.batch_mode else "benchmark")
        cmd_fallback = self._build_command("benchmark")

        def _run(cmd_to_run: List[str]) -> tuple[int, str]:
            logger.info("Running PTS command: %s", " ".join(cmd_to_run))
            self._process = subprocess.Popen(
                cmd_to_run,
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
            deadline = (start + self.config.timeout_seconds) if self.config.timeout_seconds else None
            menu_responses = 0
            while True:
                if deadline and time.time() > deadline:
                    raise subprocess.TimeoutExpired(cmd_to_run, self.config.timeout_seconds)
                line = self._process.stdout.readline()
                if not line and self._process.poll() is not None:
                    break
                if line:
                    print(line, end="", flush=True)
                    output_lines.append(line)
                    if _looks_like_menu_prompt(line) and menu_responses < 3:
                        try:
                            # Default to first configuration to keep execution non-interactive.
                            self._process.stdin.write("1\n")
                            self._process.stdin.flush()
                            menu_responses += 1
                        except Exception:
                            pass
            rc = self._process.wait()
            return rc, "".join(output_lines)

        try:
            rc, out = _run(cmd)
            # If batch mode is not supported or not configured, fall back to benchmark.
            if rc != 0 and self.config.batch_mode and any(
                token in out.lower()
                for token in (
                    "unknown command",
                    "invalid command",
                    "not a supported command",
                    "the batch mode must first be configured",
                )
            ):
                rc, out = _run(cmd_fallback)

            output_lower = out.lower()
            if (
                "[problem]" in output_lower
                or "the batch mode must first be configured" in output_lower
                or "unable to locate package" in output_lower
                or "has no installation candidate" in output_lower
                or "the update command takes no arguments" in output_lower
            ):
                if rc == 0:
                    rc = 2

            pts_result_dir: str | None = None
            pts_result_id: str | None = None
            try:
                if results_root.exists():
                    candidates = [p for p in results_root.iterdir() if p.is_dir()]
                else:
                    candidates = []
                new_dirs = [p for p in candidates if p.name not in before]
                picked = None
                if new_dirs:
                    picked = max(new_dirs, key=lambda p: p.stat().st_mtime)
                elif candidates:
                    picked = max(candidates, key=lambda p: p.stat().st_mtime)
                if picked:
                    pts_result_dir = str(picked.resolve())
                    pts_result_id = picked.name
            except Exception:
                pts_result_dir = None
                pts_result_id = None

            self._result = {
                "command": " ".join(cmd),
                "profile": self.profile,
                "returncode": rc,
                "stdout": out,
                "pts_result_dir": pts_result_dir,
                "pts_result_id": pts_result_id,
                "duration_seconds": round(time.time() - start, 3),
            }
        except subprocess.TimeoutExpired:
            self._stop_workload()
            self._result = {
                "command": " ".join(cmd),
                "profile": self.profile,
                "returncode": -1,
                "error": f"Timeout after {self.config.timeout_seconds}s",
                "duration_seconds": round(time.time() - start, 3),
            }
        except Exception as exc:
            self._result = {
                "command": " ".join(cmd),
                "profile": self.profile,
                "returncode": -2,
                "error": str(exc),
                "duration_seconds": round(time.time() - start, 3),
            }
        finally:
            self._process = None
            self._is_running = False

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
    """A single PTS test-profile exposed as a WorkloadPlugin."""

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
        combined_packages = sorted(set(self._defaults.apt_packages + self._spec.apt_packages))
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
                logger.debug("Failed to copy PTS results from %s to %s: %s", src_path, dest, exc)

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
        csv_path.write_text(
            "\n".join(
                [
                    "run_id,workload,repetition,success,duration_seconds,profile,returncode",
                    *[
                        ",".join(
                            [
                                str(r.get("run_id", "")),
                                str(r.get("workload", "")),
                                str(r.get("repetition", "")),
                                str(r.get("success", "")),
                                str(r.get("duration_seconds", "")),
                                str(r.get("profile", "")),
                                str(r.get("returncode", "")),
                            ]
                        )
                        for r in rows
                    ],
                ]
            )
            + "\n"
        )
        return [csv_path]


def _load_manifest(path: Path) -> tuple[PtsDefaults, List[PtsWorkloadSpec]]:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError("PTS config must be a YAML mapping")

    pts_data = data.get("pts") or {}
    if not isinstance(pts_data, dict):
        raise ValueError("pts section must be a mapping")

    binary = str(pts_data.get("binary") or "phoronix-test-suite")
    deb_relpath = str(pts_data.get("deb_path") or "").strip()
    if not deb_relpath:
        raise ValueError("pts.deb_path is required")
    apt_packages_raw = pts_data.get("apt_packages") or []
    if not isinstance(apt_packages_raw, list) or not all(isinstance(x, str) for x in apt_packages_raw):
        raise ValueError("pts.apt_packages must be a list of strings")
    home_root = str(pts_data.get("home_root") or "/opt/lb/.phoronix-test-suite/").strip()
    home_root = _ensure_trailing_sep(home_root)
    defaults = PtsDefaults(
        binary=binary,
        deb_relpath=deb_relpath,
        apt_packages=list(apt_packages_raw),
        home_root=home_root,
    )

    raw_workloads = data.get("workloads") or []
    if not isinstance(raw_workloads, list):
        raise ValueError("workloads must be a list")

    specs: List[PtsWorkloadSpec] = []
    for item in raw_workloads:
        if isinstance(item, str):
            profile = item.strip()
            plugin_name = _derive_plugin_name(profile)
            specs.append(
                PtsWorkloadSpec(
                    profile=profile,
                    plugin_name=plugin_name,
                    description=f"PTS profile: {profile}",
                    tags=["pts"],
                    args=[],
                    apt_packages=[],
                    expected_runtime_seconds=None,
                )
            )
            continue
        if isinstance(item, dict):
            profile = str(item.get("profile") or "").strip()
            if not profile:
                raise ValueError("workloads entry missing 'profile'")
            plugin_name = str(item.get("plugin_name") or _derive_plugin_name(profile)).strip()
            description = str(item.get("description") or f"PTS profile: {profile}").strip()
            tags_raw = item.get("tags") or ["pts"]
            if not isinstance(tags_raw, list) or not all(isinstance(x, str) for x in tags_raw):
                raise ValueError(f"workload {profile}: tags must be a list of strings")
            args_raw = item.get("args") or []
            if not isinstance(args_raw, list) or not all(isinstance(x, str) for x in args_raw):
                raise ValueError(f"workload {profile}: args must be a list of strings")
            apt_raw = item.get("apt_packages") or []
            if not isinstance(apt_raw, list) or not all(isinstance(x, str) for x in apt_raw):
                raise ValueError(f"workload {profile}: apt_packages must be a list of strings")
            expected_runtime_seconds = item.get("expected_runtime_seconds")
            if expected_runtime_seconds is not None and not isinstance(expected_runtime_seconds, int):
                raise ValueError(f"workload {profile}: expected_runtime_seconds must be int")
            specs.append(
                PtsWorkloadSpec(
                    profile=profile,
                    plugin_name=plugin_name,
                    description=description,
                    tags=list(tags_raw),
                    args=list(args_raw),
                    apt_packages=list(apt_raw),
                    expected_runtime_seconds=expected_runtime_seconds,
                )
            )
            continue
        raise ValueError("workloads entries must be strings or mappings")

    names = [s.plugin_name for s in specs]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"Duplicate plugin_name(s) in PTS config: {sorted(dupes)}")

    return defaults, specs


def get_plugins() -> List[WorkloadPlugin]:
    """
    Return virtual PTS workload plugins driven by `pts_workloads.yaml`.

    This is intentionally evaluated at registry creation time so editing the YAML
    is sufficient to add/remove workloads.
    """
    config_path = Path(__file__).with_name("pts_workloads.yaml")
    defaults, specs = _load_manifest(config_path)
    ansible_setup_path = Path(__file__).parent / "ansible" / "setup.yml"
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
    logger.debug("PTS plugin bundle created %s workload(s): %s", len(plugins), json.dumps([p.name for p in plugins]))
    return plugins
