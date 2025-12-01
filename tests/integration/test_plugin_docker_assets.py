"""Docker build/run smoke tests for plugin Dockerfiles."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from linux_benchmark_lib.plugin_system.builtin import builtin_plugins
from linux_benchmark_lib.plugin_system.registry import PluginRegistry

DOCKER_ENV_FLAG = "DOCKER_TESTS"


@dataclass
class DockerStatus:
    ready: bool
    reason: str


def _docker_status() -> DockerStatus:
    if shutil.which("docker") is None:
        return DockerStatus(False, "docker CLI not found")
    info = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if info.returncode != 0:
        return DockerStatus(False, f"docker daemon unavailable: {info.stderr or info.stdout}")
    # Auto-enable if not set
    os.environ.setdefault(DOCKER_ENV_FLAG, "1")
    return DockerStatus(True, "")


def _collect_docker_plugins() -> list[tuple[str, Path]]:
    registry = PluginRegistry(builtin_plugins())
    items: list[tuple[str, Path]] = []
    for plugin in registry.available().values():
        dockerfile = plugin.get_dockerfile_path()
        if dockerfile and dockerfile.exists():
            items.append((plugin.name, dockerfile))
    return items


DOCKER_PLUGINS = _collect_docker_plugins()

if not DOCKER_PLUGINS:
    pytest.skip("No plugin Dockerfiles found", allow_module_level=True)

DOCKER_READY = _docker_status()


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.skipif(not DOCKER_READY.ready, reason=DOCKER_READY.reason or "docker unavailable")
@pytest.mark.parametrize("plugin_name,dockerfile", DOCKER_PLUGINS)
def test_plugin_dockerfile_builds_and_runs(plugin_name: str, dockerfile: Path) -> None:
    """Build each plugin Dockerfile and run a trivial container."""
    tag = f"lb-plugin-{plugin_name}-{uuid.uuid4().hex[:8]}"
    context = dockerfile.parent

    build = subprocess.run(
        ["docker", "build", "-t", tag, "-f", str(dockerfile), str(context)],
        capture_output=True,
        text=True,
    )
    if build.returncode != 0:
        pytest.fail(
            f"Docker build failed for {plugin_name}\nstdout:\n{build.stdout}\nstderr:\n{build.stderr}"
        )

    try:
        run = subprocess.run(
            ["docker", "run", "--rm", tag, "true"],
            capture_output=True,
            text=True,
        )
        if run.returncode != 0:
            pytest.fail(
                f"Docker run failed for {plugin_name}\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}"
            )
    finally:
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)
