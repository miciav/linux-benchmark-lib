"""Integration tests for Loki handler and Grafana client with real containers."""

from __future__ import annotations

import json
import logging
import shutil
import socket
import subprocess
import time
import uuid
from urllib.request import urlopen, Request
from urllib.error import URLError

import pytest

from lb_common.handlers.loki_handler import LokiPushHandler, normalize_loki_endpoint
from lb_plugins.plugins.dfaas.services.grafana_client import GrafanaClient

pytestmark = [pytest.mark.inter_docker, pytest.mark.inter_generic]


def _docker_available() -> bool:
    """Check if Docker is available and running."""
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(["docker", "info"], capture_output=True)
    return result.returncode == 0


def _free_port() -> int:
    """Get a free port on localhost."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return int(port)


def _wait_for_http(url: str, timeout: float = 30.0, interval: float = 0.5) -> bool:
    """Wait for HTTP endpoint to become available."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def _container_cleanup(*names: str) -> None:
    """Remove Docker containers by name."""
    for name in names:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


# -----------------------------------------------------------------------------
# Loki Integration Tests
# -----------------------------------------------------------------------------


class TestLokiIntegration:
    """Integration tests for LokiPushHandler with real Loki container."""

    @pytest.fixture
    def loki_container(self):
        """Start a Loki container and yield the endpoint URL."""
        if not _docker_available():
            pytest.skip("Docker not available")

        container_name = f"loki-test-{uuid.uuid4().hex[:8]}"
        port = _free_port()

        try:
            # Start Loki container
            result = subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", container_name,
                    "-p", f"{port}:3100",
                    "grafana/loki:2.9.0",
                    "-config.file=/etc/loki/local-config.yaml",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                pytest.skip(f"Failed to start Loki container: {result.stderr}")

            endpoint = f"http://localhost:{port}"

            # Wait for Loki to be ready
            if not _wait_for_http(f"{endpoint}/ready", timeout=30.0):
                pytest.skip("Loki did not become ready in time")

            yield endpoint

        finally:
            _container_cleanup(container_name)

    def test_loki_handler_pushes_logs(self, loki_container: str):
        """Verify LokiPushHandler successfully pushes logs to Loki."""
        handler = LokiPushHandler(
            endpoint=loki_container,
            component="test-runner",
            host="integration-host",
            run_id="test-run-001",
            batch_size=1,  # Push immediately
            flush_interval=0.1,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))

        # Create and emit a log record
        record = logging.LogRecord(
            name="test.integration",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Integration test log message",
            args=(),
            exc_info=None,
        )
        handler.emit(record)

        # Give time for async push
        time.sleep(1.0)
        handler.close()

        # Query Loki to verify the log was received
        query_url = (
            f"{loki_container}/loki/api/v1/query"
            f"?query={{component=\"test-runner\",run_id=\"test-run-001\"}}"
        )
        try:
            with urlopen(query_url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert data.get("status") == "success"
                # Check if we got any results
                results = data.get("data", {}).get("result", [])
                assert len(results) > 0, "Expected at least one log entry in Loki"
        except URLError as e:
            pytest.fail(f"Failed to query Loki: {e}")

    def test_loki_handler_batches_logs(self, loki_container: str):
        """Verify LokiPushHandler batches multiple logs correctly."""
        handler = LokiPushHandler(
            endpoint=loki_container,
            component="batch-test",
            host="integration-host",
            run_id="test-run-batch",
            batch_size=5,
            flush_interval=0.5,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))

        # Emit multiple records
        for i in range(10):
            record = logging.LogRecord(
                name="test.batch",
                level=logging.INFO,
                pathname=__file__,
                lineno=i,
                msg=f"Batch message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        # Wait for flush
        time.sleep(2.0)
        handler.close()

        # Query and verify
        query_url = (
            f"{loki_container}/loki/api/v1/query"
            f"?query={{component=\"batch-test\"}}&limit=20"
        )
        with urlopen(query_url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("status") == "success"
            results = data.get("data", {}).get("result", [])
            # Should have received logs
            assert len(results) > 0


# -----------------------------------------------------------------------------
# Grafana Integration Tests
# -----------------------------------------------------------------------------


class TestGrafanaIntegration:
    """Integration tests for GrafanaClient with real Grafana container."""

    @pytest.fixture
    def grafana_container(self):
        """Start a Grafana container and yield the client."""
        if not _docker_available():
            pytest.skip("Docker not available")

        container_name = f"grafana-test-{uuid.uuid4().hex[:8]}"
        port = _free_port()

        try:
            # Start Grafana container with anonymous auth enabled
            result = subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", container_name,
                    "-p", f"{port}:3000",
                    "-e", "GF_AUTH_ANONYMOUS_ENABLED=true",
                    "-e", "GF_AUTH_ANONYMOUS_ORG_ROLE=Admin",
                    "-e", "GF_SECURITY_ADMIN_PASSWORD=admin",
                    "grafana/grafana:10.2.0",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                pytest.skip(f"Failed to start Grafana container: {result.stderr}")

            base_url = f"http://localhost:{port}"

            # Wait for Grafana to be ready
            if not _wait_for_http(f"{base_url}/api/health", timeout=60.0):
                pytest.skip("Grafana did not become ready in time")

            # Give extra time for full initialization
            time.sleep(2.0)

            client = GrafanaClient(base_url=base_url)
            yield client

        finally:
            _container_cleanup(container_name)

    def test_grafana_health_check(self, grafana_container: GrafanaClient):
        """Verify GrafanaClient can perform health check."""
        healthy, data = grafana_container.health_check()
        assert healthy is True
        assert data is not None

    def test_grafana_upsert_datasource(self, grafana_container: GrafanaClient):
        """Verify GrafanaClient can create and update datasources."""
        # Create datasource
        ds_id = grafana_container.upsert_datasource(
            name="test-prometheus",
            url="http://prometheus:9090",
            datasource_type="prometheus",
            is_default=False,
        )
        assert ds_id is not None
        assert isinstance(ds_id, int)

        # Update same datasource (upsert)
        ds_id_updated = grafana_container.upsert_datasource(
            name="test-prometheus",
            url="http://prometheus:9091",  # Changed URL
            datasource_type="prometheus",
            is_default=True,
        )
        assert ds_id_updated == ds_id  # Same ID means update worked

    def test_grafana_import_dashboard(self, grafana_container: GrafanaClient):
        """Verify GrafanaClient can import dashboards."""
        # Simple test dashboard
        dashboard = {
            "title": "Integration Test Dashboard",
            "uid": "test-integration-dash",
            "panels": [
                {
                    "id": 1,
                    "title": "Test Panel",
                    "type": "stat",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                }
            ],
            "schemaVersion": 38,
        }

        result = grafana_container.import_dashboard(dashboard, overwrite=True)
        assert result is not None
        assert result.get("status") == "success"
        assert result.get("uid") == "test-integration-dash"

    def test_grafana_create_annotation(self, grafana_container: GrafanaClient):
        """Verify GrafanaClient can create annotations."""
        result = grafana_container.create_annotation(
            text="Integration test annotation",
            tags=["test", "integration"],
        )
        assert result is not None
        assert "id" in result


# -----------------------------------------------------------------------------
# Combined Integration Test
# -----------------------------------------------------------------------------


class TestLokiGrafanaCombined:
    """Integration test combining Loki and Grafana setup."""

    @pytest.fixture
    def loki_grafana_stack(self):
        """Start both Loki and Grafana containers."""
        if not _docker_available():
            pytest.skip("Docker not available")

        suffix = uuid.uuid4().hex[:8]
        loki_name = f"loki-combined-{suffix}"
        grafana_name = f"grafana-combined-{suffix}"
        loki_port = _free_port()
        grafana_port = _free_port()

        try:
            # Start Loki
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", loki_name,
                    "-p", f"{loki_port}:3100",
                    "grafana/loki:2.9.0",
                    "-config.file=/etc/loki/local-config.yaml",
                ],
                capture_output=True,
                check=True,
            )

            # Start Grafana
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", grafana_name,
                    "-p", f"{grafana_port}:3000",
                    "-e", "GF_AUTH_ANONYMOUS_ENABLED=true",
                    "-e", "GF_AUTH_ANONYMOUS_ORG_ROLE=Admin",
                    "grafana/grafana:10.2.0",
                ],
                capture_output=True,
                check=True,
            )

            loki_url = f"http://localhost:{loki_port}"
            grafana_url = f"http://localhost:{grafana_port}"

            # Wait for both to be ready
            if not _wait_for_http(f"{loki_url}/ready", timeout=30.0):
                pytest.skip("Loki did not become ready")
            if not _wait_for_http(f"{grafana_url}/api/health", timeout=60.0):
                pytest.skip("Grafana did not become ready")

            time.sleep(2.0)

            yield {
                "loki_url": loki_url,
                "grafana_url": grafana_url,
                "grafana_client": GrafanaClient(base_url=grafana_url),
            }

        finally:
            _container_cleanup(loki_name, grafana_name)

    def test_grafana_loki_datasource_setup(self, loki_grafana_stack: dict):
        """Test setting up Loki as a Grafana datasource."""
        client = loki_grafana_stack["grafana_client"]
        loki_url = loki_grafana_stack["loki_url"]

        # Create Loki datasource in Grafana
        ds_id = client.upsert_datasource(
            name="Loki",
            url=loki_url,
            datasource_type="loki",
            is_default=False,
        )
        assert ds_id is not None

        # Verify datasource exists
        status, data = client._request(
            "GET",
            f"/api/datasources/{ds_id}",
            expected_statuses={200},
        )
        assert status == 200
        assert data["name"] == "Loki"
        assert data["type"] == "loki"
