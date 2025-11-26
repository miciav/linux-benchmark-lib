"""Container-based runner for executing the CLI inside Docker/Podman."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from benchmark_config import BenchmarkConfig
from services.plugin_service import create_registry
from plugins.interface import WorkloadPlugin


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


class ContainerRunner:
    """Build and execute the CLI inside a container."""

    def __init__(self) -> None:
        self.registry = create_registry()

    def ensure_engine(self, engine: str) -> None:
        """Verify the container engine is available."""
        if shutil.which(engine) is None:
            raise RuntimeError(f"{engine} not found in PATH")

    def build_image(self, spec: ContainerRunSpec) -> None:
        """Build the image if requested (legacy monolithic build)."""
        if not spec.build:
            return
        cmd = [spec.engine, "build", "-t", spec.image, str(spec.workdir)]
        if spec.no_cache:
            cmd.append("--no-cache")
        subprocess.run(cmd, check=True)

    def build_plugin_image(self, spec: ContainerRunSpec, plugin: WorkloadPlugin) -> str:
        """
        Build a dedicated image for the plugin if a specific Dockerfile exists.
        Otherwise, fall back to the main image.
        """
        dockerfile = plugin.get_dockerfile_path()
        
        # If no specific Dockerfile, use the legacy/root one
        if not dockerfile or not dockerfile.exists():
            self.build_image(spec)
            return spec.image

        image_tag = f"lb-plugin-{plugin.name}"
        if not spec.build:
            return image_tag

        # Build context is usually the root of the project to allow copying shared libs if needed
        # But strictly speaking, a modular plugin should be self-contained or pip-install the lib.
        # For now, we use spec.workdir (project root) as context, but point to the specific Dockerfile.
        
        cmd = [
            spec.engine,
            "build",
            "-t",
            image_tag,
            "-f",
            str(dockerfile),
            str(spec.workdir)
        ]
        if spec.no_cache:
            cmd.append("--no-cache")
            
        print(f"Building specific image for {plugin.name} using {dockerfile}...")
        subprocess.run(cmd, check=True)
        return image_tag

    def run_workload(self, spec: ContainerRunSpec, workload_name: str, plugin: WorkloadPlugin) -> None:
        """Run a single workload in its specific container."""
        self.ensure_engine(spec.engine)
        
        image_tag = self.build_plugin_image(spec, plugin)

        # We execute `python3 cli.py run <workload> --no-remote` inside the container.
        # 'uv' is not installed in the minimal plugin container.
        inner_cmd = ["python3", "cli.py", "run", workload_name, "--no-remote"]
        if spec.run_id:
            inner_cmd.extend(["--run-id", spec.run_id])

        spec.artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Mount logic
        # We mount the project root to /app to allow the inner run to work 
        # on the current code (development mode).
        volume_args = [
            "-v", f"{spec.workdir}:/app",  # Mount source code
            "-v", f"{spec.artifacts_dir}:/app/benchmark_results",
        ]

        env_args: List[str] = ["-e", "PYTHONPATH=/app"]
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
            "-t",
            "-w",
            "/app",
            *volume_args,
            *env_args,
            image_tag,
            *inner_cmd,
        ]

        print(f"Running container for {workload_name} [{image_tag}]...")
        subprocess.run(cmd, check=True)

    def run(self, spec: ContainerRunSpec) -> None:
        """Execute the inner CLI run inside the container."""
        self.ensure_engine(spec.engine)
        self.build_image(spec)

        inner_cmd = ["python3", "cli.py", "run"]
        if spec.tests:
            inner_cmd.extend(spec.tests)
        if spec.run_id:
            inner_cmd.extend(["--run-id", spec.run_id])
        if spec.remote is not None:
            inner_cmd.append("--remote" if spec.remote else "--no-remote")

        spec.artifacts_dir.mkdir(parents=True, exist_ok=True)

        volume_args = [
            "-v",
            f"{spec.artifacts_dir}:/app/benchmark_results",
        ]

        env_args: List[str] = ["-e", "PYTHONPATH=/app"]
        if spec.config_path:
            cfg_host = spec.config_path.resolve()
            cfg_in_container = "/tmp/host_config.json"
            volume_args.extend(["-v", f"{cfg_host}:{cfg_in_container}:ro"])
            env_args.extend(["-e", f"LB_CONFIG_PATH={cfg_in_container}"])

        cmd = [
            spec.engine,
            "run",
            "--rm",
            "-t",
            "-w",
            "/app",
            *volume_args,
            *env_args,
            spec.image,
            *inner_cmd,
        ]

        subprocess.run(cmd, check=True)


def resolve_config_path_for_container(cfg: BenchmarkConfig, explicit: Optional[Path]) -> Optional[Path]:
    """
    Resolve the config path for container use.

    If the user passed an explicit path, return it. Otherwise, look for the saved/default.
    """
    if explicit:
        return Path(explicit).expanduser()
    return None
