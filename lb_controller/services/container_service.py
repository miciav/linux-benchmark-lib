"""Container-based runner for executing the CLI inside Docker/Podman."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Callable

from lb_runner.benchmark_config import BenchmarkConfig
from .plugin_service import create_registry
from lb_runner.plugin_system.interface import WorkloadPlugin
from lb_controller.ui_interfaces import UIAdapter


@dataclass
class ContainerRunSpec:
    """Parameters needed to execute a run inside a container."""

    tests: List[str]
    cfg_path: Optional[Path]
    config_path: Optional[Path]
    run_id: Optional[str]
    remote: Optional[bool]
    image: str
    workdir: Path
    artifacts_dir: Path
    engine: str = "docker"  # or "podman"
    build: bool = True
    no_cache: bool = False
    debug: bool = False
    repetitions: int | None = None


class ContainerRunner:
    """Build and execute the CLI inside a container."""

    def __init__(self) -> None:
        self.registry = create_registry()

    def ensure_engine(self, engine: str) -> None:
        """Verify the container engine is available."""
        if shutil.which(engine) is None:
            raise RuntimeError(f"{engine} not found in PATH")

    def build_plugin_image(
        self,
        spec: ContainerRunSpec,
        plugin: WorkloadPlugin,
        ui_adapter: UIAdapter | None = None,
    ) -> str:
        """
        Build a dedicated image for the plugin using its specific Dockerfile.
        """
        dockerfile = plugin.get_dockerfile_path()
        
        if not dockerfile or not dockerfile.exists():
            raise RuntimeError(
                f"Plugin '{plugin.name}' does not provide a Dockerfile. "
                "Container execution is not supported for this plugin."
            )

        image_tag = f"lb-plugin-{plugin.name}"
        if not spec.build:
            return image_tag

        # Derive build context: prefer a pyproject root adjacent to the Dockerfile, else use Dockerfile parent,
        # else fall back to the user-provided workdir.
        context_dir = spec.workdir
        docker_parent = dockerfile.parent
        # If Dockerfile sits inside a package subdir (e.g., pkg/Dockerfile) and pyproject is one level up, use that.
        if not (docker_parent / "pyproject.toml").exists() and (docker_parent.parent / "pyproject.toml").exists():
            context_dir = docker_parent.parent
        elif (docker_parent / "pyproject.toml").exists():
            context_dir = docker_parent

        cmd = [
            spec.engine,
            "build",
            "-t",
            image_tag,
            "-f",
            str(dockerfile),
            str(context_dir)
        ]
        if spec.no_cache:
            cmd.append("--no-cache")
            
        message = f"Building container image for {plugin.name}..."
        if ui_adapter:
            ui_adapter.show_info(message)
        else:
            print(message)

        if spec.debug:
            subprocess.run(cmd, check=True)
        else:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"Failed to build image '{image_tag}' for {plugin.name}: "
                    f"{result.stderr or result.stdout}"
                )
            if ui_adapter:
                ui_adapter.show_success(f"Image ready: {image_tag}")
            else:
                print(f"Image ready: {image_tag}")
        return image_tag

    def run_workload(
        self,
        spec: ContainerRunSpec,
        workload_name: str,
        plugin: WorkloadPlugin,
        ui_adapter: UIAdapter | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> str | None:
        """Run a single workload in its specific container."""
        self.ensure_engine(spec.engine)

        if ui_adapter:
            image_tag = self.build_plugin_image(spec, plugin, ui_adapter=ui_adapter)
        else:
            image_tag = self.build_plugin_image(spec, plugin)

        # We execute the package CLI module inside the container (no uv in the minimal image).
        inner_cmd = [
            "python3",
            "-u",  # Force unbuffered binary stdout
            "-m",
            "lb_ui.cli",
            "run",
            workload_name,
            "--no-remote",
            "--no-setup",  # Avoid ansible-runner in container images built for workload-only execution
        ]
        run_id = spec.run_id or workload_name
        inner_cmd.extend(["--run-id", run_id])
        if spec.debug:
            inner_cmd.append("--debug")
        if spec.repetitions and spec.repetitions > 0:
            inner_cmd.extend(["--repetitions", str(spec.repetitions)])

        spec.artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Mount logic
        # We mount the project root to /app to allow the inner run to work
        # on the current code (development mode).
        volume_args = [
            "-v", f"{spec.workdir}:/app",  # Mount source code
            "-v", f"{spec.artifacts_dir}:/app/benchmark_results",
        ]

        env_args: List[str] = [
            "-e", "PYTHONPATH=/app",
            "-e", "LB_CONTAINER_MODE=1",
            "-e", "PYTHONUNBUFFERED=1",
            "-e", "LB_ENABLE_EVENT_LOGGING=1",
        ]
        if spec.config_path:
            cfg_host = spec.config_path.resolve()
            cfg_in_container = "/tmp/host_config.json"
            # Ensure local config dir exists mapped into container if needed,
            # but mapping single file is safer.
            # However, if we map /app (workdir), we might shadow config.
            # Let's just map the config file explicitly.
            volume_args.extend(["-v", f"{cfg_host}:{cfg_in_container}:ro"])
            env_args.extend(["-e", f"LB_CONFIG_PATH={cfg_in_container}"])

        cmd = [
            spec.engine,
            "run",
            "--rm",
            "--name",
            f"lb-{workload_name}-{run_id}",
            "-w",
            "/app",
            *volume_args,
            *env_args,
            image_tag,
            *inner_cmd,
        ]

        print(f"Running container for {workload_name} [{image_tag}]...")
        print(f"Container command: {' '.join(cmd)}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            bufsize=1,  # Line buffered
        )

        captured_stdout: list[str] = []
        if process.stdout:
            for line in process.stdout:
                # Invoke callback if provided (e.g. for UI updates)
                if output_callback:
                    output_callback(line)
                else:
                    print(line, end="")
                captured_stdout.append(line)

        process.wait()
        full_output = "".join(captured_stdout)

        if process.returncode != 0:
            raise RuntimeError(f"Container run failed (rc={process.returncode})")

        inner_run_id = self._extract_run_id(full_output) or run_id
        return inner_run_id

    @staticmethod
    def _extract_run_id(output: str) -> str | None:
        """Parse LB_EVENT lines to recover the run_id emitted inside the container."""
        if not output:
            return None
        import json  # Local import to avoid overhead when unused
        latest = None
        for line in output.splitlines():
            token_idx = line.find("LB_EVENT")
            if token_idx == -1:
                continue
            payload = line[token_idx + len("LB_EVENT"):].strip()
            if "{" not in payload or "}" not in payload:
                continue
            start = payload.find("{")
            end = payload.rfind("}") + 1
            candidate = payload[start:end]
            for attempt in (candidate, candidate.replace(r"\"", '"')):
                try:
                    data = json.loads(attempt)
                    rid = data.get("run_id")
                    if rid:
                        latest = rid
                except Exception:
                    continue
        return latest


def resolve_config_path_for_container(cfg: BenchmarkConfig, explicit: Optional[Path]) -> Optional[Path]:
    """
    Resolve the config path for container use.

    If the user passed an explicit path, return it. Otherwise, look for the saved/default.
    """
    if explicit:
        return Path(explicit).expanduser()
    return None
