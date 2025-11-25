"""Container-based runner for executing the CLI inside Docker/Podman."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from benchmark_config import BenchmarkConfig
from services.plugin_service import create_registry


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
        """Build the image if requested."""
        if not spec.build:
            return
        cmd = [spec.engine, "build", "-t", spec.image, str(spec.workdir)]
        if spec.no_cache:
            cmd.append("--no-cache")
        subprocess.run(cmd, check=True)

    def run(self, spec: ContainerRunSpec) -> None:
        """Execute the inner CLI run inside the container."""
        self.ensure_engine(spec.engine)
        self.build_image(spec)

        inner_cmd = ["uv", "run", "lb", "run"]
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

        env_args: List[str] = []
        if spec.config_path:
            cfg_host = spec.config_path.resolve()
            cfg_in_container = "/app/config/host_config.json"
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
