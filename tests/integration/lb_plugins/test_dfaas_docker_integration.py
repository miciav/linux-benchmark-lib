from __future__ import annotations

import os
import shutil
import socket
import subprocess
import textwrap
import time
import uuid
from pathlib import Path
from urllib.request import urlopen

import pytest

from lb_plugins.plugins.peva_faas.generator import DfaasGenerator
from lb_plugins.plugins.peva_faas.config import DfaasConfig, DfaasFunctionConfig
from lb_plugins.plugins.peva_faas.plugin import DfaasPlugin

pytestmark = [pytest.mark.inter_plugins, pytest.mark.inter_docker]


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _ensure_image(image: str) -> None:
    inspect = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
    if inspect.returncode == 0:
        return
    pull = subprocess.run(["docker", "pull", image], capture_output=True)
    if pull.returncode != 0:
        pytest.skip(f"Unable to pull Docker image {image!r}.")


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return int(port)


def _wait_for_ready(url: str, timeout: float = 10.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    pytest.skip(f"Target server did not become ready: {url}")


def _write_stub(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _docker_cleanup(names: list[str], network: str) -> None:
    for name in names:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(["docker", "network", "rm", network], capture_output=True)


class _DockerResult:
    def __init__(self, stdout: str, stderr: str, exited: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exited = exited
        self.failed = exited != 0


class _DockerConnection:
    def __init__(self, container: str) -> None:
        self._container = container

    def run(self, command: str, **kwargs: object) -> _DockerResult:
        result = subprocess.run(
            ["docker", "exec", "-u", "0", self._container, "/bin/sh", "-c", command],
            capture_output=True,
            text=True,
        )
        out_stream = kwargs.get("out_stream")
        if out_stream and result.stdout:
            try:
                out_stream.write(result.stdout)
            except Exception:
                pass
        if result.returncode != 0 and not kwargs.get("warn", False):
            raise RuntimeError(result.stderr or result.stdout)
        return _DockerResult(result.stdout, result.stderr, result.returncode)

    def put(self, local: str, remote: str) -> None:
        subprocess.run(
            ["docker", "cp", local, f"{self._container}:{remote}"],
            check=True,
            capture_output=True,
        )

    def get(self, remote: str, local: str) -> None:
        subprocess.run(
            ["docker", "cp", f"{self._container}:{remote}", local],
            check=True,
            capture_output=True,
        )

    def close(self) -> None:
        return None


def test_dfaas_end_to_end_with_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not _docker_available():
        pytest.skip("Docker not available.")

    _ensure_image("python:3.12-slim")
    _ensure_image("grafana/k6:0.49.0")

    suffix = uuid.uuid4().hex[:8]
    network = f"dfaas-net-{suffix}"
    target_name = f"dfaas-target-{suffix}"
    k6_name = f"dfaas-k6-{suffix}"
    host_port = _free_port()

    server_script = textwrap.dedent(
        """
        import json
        import time
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _send_json(self, payload):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path.startswith("/function/"):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")
                    return
                if self.path.startswith("/-/ready"):
                    self.send_response(200)
                    self.end_headers()
                    return
                now = int(time.time())
                if self.path.startswith("/api/v1/query_range"):
                    payload = {
                        "status": "success",
                        "data": {
                            "resultType": "matrix",
                            "result": [
                                {"metric": {}, "values": [[now, "1.0"], [now + 1, "1.0"]]}
                            ],
                        },
                    }
                    self._send_json(payload)
                    return
                if self.path.startswith("/api/v1/query"):
                    payload = {
                        "status": "success",
                        "data": {
                            "resultType": "vector",
                            "result": [{"metric": {}, "value": [now, "1.0"]}],
                        },
                    }
                    self._send_json(payload)
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                if self.path.startswith("/function/"):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")
                    return
                self.send_response(404)
                self.end_headers()

        if __name__ == "__main__":
            server = HTTPServer(("0.0.0.0", 8000), Handler)
            server.serve_forever()
        """
    ).strip()

    script_path = tmp_path / "server.py"
    script_path.write_text(server_script)

    try:
        subprocess.run(["docker", "network", "create", network], check=True)
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                target_name,
                "--network",
                network,
                "-p",
                f"{host_port}:8000",
                "-v",
                f"{script_path}:/srv/server.py:ro",
                "python:3.12-slim",
                "python",
                "/srv/server.py",
            ],
            check=True,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                k6_name,
                "--network",
                network,
                "--entrypoint",
                "/bin/sh",
                "grafana/k6:0.49.0",
                "-c",
                "sleep infinity",
            ],
            check=True,
        )

        _wait_for_ready(f"http://127.0.0.1:{host_port}/-/ready")
        monkeypatch.setattr(
            "lb_plugins.plugins.peva_faas.services.k6_runner.K6Runner._get_connection",
            lambda self: _DockerConnection(k6_name),
        )

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        ansible_stub = textwrap.dedent(
            f"""
            #!/bin/sh
            set -e
            SCRIPT_SRC=""
            SUMMARY_FETCH_DEST=""
            while [ "$#" -gt 0 ]; do
              case "$1" in
                script_src=*) SCRIPT_SRC="${{1#script_src=}}" ;;
                summary_fetch_dest=*) SUMMARY_FETCH_DEST="${{1#summary_fetch_dest=}}" ;;
              esac
              shift
            done
            if [ -z "$SCRIPT_SRC" ]; then
              echo "missing script_src" >&2
              exit 1
            fi
            docker cp "$SCRIPT_SRC" {k6_name}:/tmp/script.js
            docker exec {k6_name} k6 run --summary-export /tmp/summary.json /tmp/script.js > /tmp/k6.log 2>&1
            if [ -n "$SUMMARY_FETCH_DEST" ]; then
              mkdir -p "$SUMMARY_FETCH_DEST"
              docker cp {k6_name}:/tmp/summary.json "$SUMMARY_FETCH_DEST/summary.json"
            fi
            """
        ).strip()
        _write_stub(bin_dir / "ansible-playbook", ansible_stub)

        faas_stub = textwrap.dedent(
            """
            #!/bin/sh
            if [ "$1" = "list" ]; then
              echo "NAME INVOCATIONS REPLICAS"
              echo "figlet 0 1"
              echo "eat-memory 0 1"
              exit 0
            fi
            exit 0
            """
        ).strip()
        _write_stub(bin_dir / "faas-cli", faas_stub)

        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("LB_RUN_HOST", "dfaas-target")

        dummy_key = tmp_path / "dummy_key"
        dummy_key.write_text("dummy")

        output_dir = tmp_path / "dfaas_output"
        run_id = "run-dfaas-integration"
        cfg = DfaasConfig(
            output_dir=output_dir,
            run_id=run_id,
            k6_host=k6_name,
            k6_user="root",
            k6_ssh_key=str(dummy_key),
            k6_port=22,
            gateway_url=f"http://{target_name}:8000",
            prometheus_url=f"http://127.0.0.1:{host_port}",
            functions=[
                DfaasFunctionConfig(
                    name="figlet",
                    method="POST",
                    body="Hello DFaaS!",
                    headers={"Content-Type": "text/plain"},
                )
            ],
            rates={"min_rate": 1, "max_rate": 1, "step": 1},
            combinations={"min_functions": 1, "max_functions": 2},
            duration="2s",
            iterations=1,
            cooldown={"max_wait_seconds": 5, "sleep_step_seconds": 1, "idle_threshold_pct": 15},
            queries_path=str(Path("lb_plugins/plugins/peva_faas/queries.yml").resolve()),
        )

        generator = DfaasGenerator(cfg)
        generator.start()
        timeout = time.time() + 60
        while getattr(generator, "_is_running", False) and time.time() < timeout:
            time.sleep(0.2)
        assert getattr(generator, "_is_running", False) is False
        result = generator.get_result()
        assert isinstance(result, dict)
        assert result.get("success") is True

        plugin = DfaasPlugin()
        plugin.export_results_to_csv(
            results=[{"repetition": 1, "generator_result": result}],
            output_dir=output_dir,
            run_id=run_id,
            test_name="dfaas",
        )

        assert (output_dir / "results.csv").exists()
        assert (output_dir / "skipped.csv").exists()
        assert (output_dir / "index.csv").exists()
        assert list((output_dir / "summaries").glob("summary-*.json"))
        assert list((output_dir / "metrics").glob("metrics-*.csv"))
        assert list((output_dir / "k6_scripts").glob("config-*.js"))
    finally:
        _docker_cleanup([target_name, k6_name], network)
