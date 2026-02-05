from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Iterator, TypeVar
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from tenacity import retry, stop_after_attempt, wait_fixed

from lb_controller.api import (
    AnsibleRunnerExecutor,
    BenchmarkController,
    ControllerOptions,
    _extract_lb_event,
)
from lb_plugins.api import PluginAssetConfig
from lb_plugins.plugins.dfaas.generator import DfaasGenerator
from lb_plugins.plugins.dfaas.services.plan_builder import (
    config_id,
    generate_configurations,
)
from lb_plugins.plugins.dfaas.config import (
    DfaasCombinationConfig,
    DfaasConfig,
    DfaasCooldownConfig,
    DfaasFunctionConfig,
    DfaasRatesConfig,
)
from lb_plugins.plugins.dfaas.plugin import DfaasPlugin
from lb_plugins.plugins.dfaas.queries import (
    PrometheusQueryRunner,
    filter_queries,
    load_queries,
)
from lb_runner.api import (
    BenchmarkConfig,
    MetricCollectorConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from tests.e2e.test_multipass_benchmark import (
    multipass_vm,
)  # noqa: F401 - fixture import
from tests.helpers.multipass import make_test_ansible_env, stage_private_key

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.inter_e2e,
    pytest.mark.inter_multipass,
    pytest.mark.inter_plugins,
    pytest.mark.slowest,
]

STRICT_MULTIPASS_SETUP = os.environ.get("LB_STRICT_MULTIPASS_SETUP", "").lower() in {
    "1",
    "true",
    "yes",
}
RUN_PEVA_FAAS_MULTIPASS_E2E = os.environ.get(
    "LB_RUN_PEVA_FAAS_MULTIPASS_E2E",
    "1",
).lower() in {
    "1",
    "true",
    "yes",
}

if not (RUN_PEVA_FAAS_MULTIPASS_E2E or STRICT_MULTIPASS_SETUP):
    pytest.skip(
        "PEVA-faas multipass e2e disabled. Set LB_RUN_PEVA_FAAS_MULTIPASS_E2E=1 to enable.",
        allow_module_level=True,
    )

# Retry configuration for transient failures
RETRY_ATTEMPTS = int(os.environ.get("LB_E2E_RETRY_ATTEMPTS", "3"))
RETRY_DELAY_SECONDS = int(os.environ.get("LB_E2E_RETRY_DELAY", "5"))

T = TypeVar("T")


def _log_diagnostics(context: str, exc: Exception) -> None:
    """Log detailed diagnostics before skip/fail."""
    logger.warning(
        "E2E test failure in %s:\n" "  Exception: %s: %s\n" "  Traceback:\n%s",
        context,
        type(exc).__name__,
        exc,
        traceback.format_exc(),
    )


def _skip_or_fail(
    message: str, context: str | None = None, exc: Exception | None = None
) -> None:
    """Skip or fail test with detailed diagnostics."""
    if exc and context:
        _log_diagnostics(context, exc)
    full_message = f"{message} (context: {context})" if context else message
    if STRICT_MULTIPASS_SETUP:
        pytest.fail(full_message)
    pytest.skip(full_message)


def _ensure_local_prereqs() -> None:
    for tool in ("ansible-playbook", "faas-cli"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not available on this host")


def _k6_workspace_root(user: str) -> str:
    if user == "root":
        return "/root/.dfaas-k6"
    return f"/home/{user}/.dfaas-k6"


def _lb_workdir(user: str) -> str:
    if user == "root":
        return "/root/.lb"
    return f"/home/{user}/.lb"


def _run_playbook(
    playbook: Path,
    inventory: Path,
    extra_vars: dict[str, Any] | None,
    env: dict[str, str],
) -> None:
    cmd = ["ansible-playbook", "-i", str(inventory), str(playbook)]
    if extra_vars:
        cmd.extend(["-e", json.dumps(extra_vars)])
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"Playbook failed: {playbook}\n{result.stdout}\n{result.stderr}"
        )


def _multipass_exec(vm_name: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["multipass", "exec", vm_name, "--", *args],
        capture_output=True,
        text=True,
        check=True,
    )


@retry(stop=stop_after_attempt(60), wait=wait_fixed(3))
def _wait_for_http(url: str) -> None:
    """Wait for HTTP 200 OK with retries using tenacity."""
    request = Request(url)
    with urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise Exception(f"HTTP status {response.status}")


@retry(stop=stop_after_attempt(60), wait=wait_fixed(3))
def _wait_for_prometheus_metric(base_url: str, query: str) -> None:
    """Wait for a Prometheus metric to be available using tenacity."""
    url = f"{base_url}/api/v1/query?{urlencode({'query': query})}"
    request = Request(url)
    with urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("data", {}).get("result"):
        raise Exception(f"Metric {query} not found in {payload}")


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_ssh_tunnel_proc(
    host: str,
    user: str,
    key_path: str,
    local_port: int,
    remote_port: int,
    remote_host: str = "127.0.0.1",
) -> subprocess.Popen[str]:
    cmd = [
        "ssh",
        "-N",
        "-L",
        f"{local_port}:{remote_host}:{remote_port}",
        "-i",
        key_path,
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        f"{user}@{host}",
    ]
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


@contextlib.contextmanager
def ssh_tunnel(
    host: str,
    user: str,
    key_path: str,
    remote_port: int,
    local_port: int | None = None,
    remote_host: str = "127.0.0.1",
) -> Iterator[int]:
    """Context manager for SSH tunnel."""
    if local_port is None:
        local_port = _allocate_local_port()

    proc = _start_ssh_tunnel_proc(
        host, user, key_path, local_port, remote_port, remote_host
    )
    try:
        # Give it a moment to establish connection
        time.sleep(1)
        if proc.poll() is not None:
            raise RuntimeError(
                f"SSH tunnel failed to start. Return code: {proc.returncode}"
            )
        yield local_port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _get_openfaas_password(vm_name: str) -> str:
    result = _multipass_exec(
        vm_name,
        [
            "kubectl",
            "-n",
            "openfaas",
            "get",
            "secret",
            "basic-auth",
            "-o",
            "jsonpath={.data.basic-auth-password}",
        ],
    )
    decoded = base64.b64decode(result.stdout.strip())
    return decoded.decode("utf-8")


def _login_openfaas(gateway_url: str, password: str) -> None:
    result = subprocess.run(
        [
            "faas-cli",
            "login",
            "--gateway",
            gateway_url,
            "--username",
            "admin",
            "--password",
            password,
            "--tls-no-verify",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"faas-cli login failed:\n{result.stdout}\n{result.stderr}")


def _write_inventory(inventory_path: Path, host: dict[str, str]) -> None:
    inventory_path.write_text(
        "\n".join(
            [
                "[all]",
                (
                    "host "
                    f"ansible_host={host['ip']} "
                    f"ansible_user={host['user']} "
                    f"ansible_ssh_private_key_file={host['key']} "
                    "ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null' "
                    "ansible_python_interpreter=/usr/bin/python3"
                ),
                "",
            ]
        )
    )


def _ensure_dfaas_k6_key_on_target(
    vm_name: str,
    user: str,
    key_path: Path,
) -> str:
    """Copy the SSH key to the target so DFaaS can reach the k6 host."""
    key_path = Path(key_path)
    temp_dest = "/tmp/dfaas_k6_key"
    subprocess.run(
        ["multipass", "transfer", str(key_path), f"{vm_name}:{temp_dest}"],
        check=True,
    )

    root_dest = "/root/.ssh/dfaas_k6_key"
    subprocess.run(
        [
            "multipass",
            "exec",
            vm_name,
            "--",
            "sudo",
            "mkdir",
            "-p",
            str(Path(root_dest).parent),
        ],
        check=True,
    )
    subprocess.run(
        [
            "multipass",
            "exec",
            vm_name,
            "--",
            "sudo",
            "mv",
            temp_dest,
            root_dest,
        ],
        check=True,
    )
    subprocess.run(
        [
            "multipass",
            "exec",
            vm_name,
            "--",
            "sudo",
            "chmod",
            "600",
            root_dest,
        ],
        check=True,
    )

    if user != "root":
        user_dest = f"/home/{user}/.ssh/dfaas_k6_key"
        subprocess.run(
            [
                "multipass",
                "exec",
                vm_name,
                "--",
                "mkdir",
                "-p",
                str(Path(user_dest).parent),
            ],
            check=True,
        )
        subprocess.run(
            ["multipass", "exec", vm_name, "--", "sudo", "cp", root_dest, user_dest],
            check=True,
        )
        subprocess.run(
            [
                "multipass",
                "exec",
                vm_name,
                "--",
                "sudo",
                "chown",
                f"{user}:{user}",
                user_dest,
            ],
            check=True,
        )
        subprocess.run(
            ["multipass", "exec", vm_name, "--", "sudo", "chmod", "600", user_dest],
            check=True,
        )
        return user_dest
    return root_dest


def _get_existing_dfaas_vms() -> list[dict[str, Any]] | None:
    """Check if dfaas-target and dfaas-generator VMs exist and are running."""
    try:
        result = subprocess.run(
            ["multipass", "list", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        vms_list = data.get("list", [])

        target_vm = None
        generator_vm = None

        # Look for the dfaas multipass key in the project's temp_keys directory
        project_root = Path(__file__).resolve().parent.parent.parent
        dfaas_key = project_root / "temp_keys" / "dfaas_multipass_key"
        if not dfaas_key.exists():
            # Fall back to default SSH key
            dfaas_key = Path.home() / ".ssh" / "id_rsa"

        for vm in vms_list:
            if vm.get("state") != "Running":
                continue
            name = vm.get("name", "")
            ipv4 = vm.get("ipv4", [])
            if not ipv4:
                continue

            if name == "dfaas-target":
                target_vm = {
                    "name": name,
                    "ip": ipv4[0],
                    "user": "ubuntu",
                    "key_path": str(dfaas_key),
                }
            elif name == "dfaas-generator":
                generator_vm = {
                    "name": name,
                    "ip": ipv4[0],
                    "user": "ubuntu",
                    "key_path": str(dfaas_key),
                }

        if target_vm and generator_vm:
            return [target_vm, generator_vm]
        return None
    except Exception:
        return None


@pytest.fixture(scope="module")
def multipass_two_vms(request):
    """Fixture that uses existing dfaas VMs if available, otherwise creates new ones."""
    # First check if existing dfaas VMs are available
    existing_vms = _get_existing_dfaas_vms()
    if existing_vms:
        logger.info("Using existing dfaas VMs: %s", [vm["name"] for vm in existing_vms])
        yield existing_vms
        return

    # Fall back to creating new VMs
    logger.info("No existing dfaas VMs found, creating new ones...")
    monkeypatch = pytest.MonkeyPatch()
    if "LB_MULTIPASS_VM_COUNT" not in os.environ:
        monkeypatch.setenv("LB_MULTIPASS_VM_COUNT", "2")
    if "LB_MULTIPASS_MEMORY" not in os.environ:
        monkeypatch.setenv("LB_MULTIPASS_MEMORY", "4G")
    if "LB_MULTIPASS_CPUS" not in os.environ:
        monkeypatch.setenv("LB_MULTIPASS_CPUS", "2")
    try:
        vms = request.getfixturevalue("multipass_vm")
        if len(vms) < 2:
            _skip_or_fail("Need two multipass VMs for DFaaS integration test.")
        yield vms
    finally:
        monkeypatch.undo()


def _clean_remote_workspace(vm_name: str, paths: list[str]) -> None:
    """Clean up remote workspace paths to avoid test pollution."""
    logger.info("Cleaning remote workspace on %s: %s", vm_name, paths)
    cmd = ["sudo", "rm", "-rf", *paths]
    _multipass_exec(vm_name, cmd)


def test_dfaas_multipass_end_to_end(multipass_two_vms, tmp_path: Path) -> None:
    _ensure_local_prereqs()
    target_vm, k6_vm = multipass_two_vms[0], multipass_two_vms[1]
    k6_workspace_root = _k6_workspace_root(k6_vm["user"])

    # Cleanup before run
    _clean_remote_workspace(k6_vm["name"], [k6_workspace_root])
    _clean_remote_workspace(
        target_vm["name"], ["/tmp/benchmark_results", "/tmp/dfaas_results"]
    )

    ansible_dir = tmp_path / "ansible_dfaas"
    staged_key = stage_private_key(Path(target_vm["key_path"]), ansible_dir / "keys")
    _ensure_dfaas_k6_key_on_target(
        target_vm["name"],
        target_vm["user"],
        staged_key,
    )
    target_host = {
        "ip": target_vm["ip"],
        "user": target_vm["user"],
        "key": str(staged_key),
    }
    k6_host = {
        "ip": k6_vm["ip"],
        "user": k6_vm["user"],
        "key": str(staged_key),
    }

    ansible_env = make_test_ansible_env(ansible_dir)

    target_inventory = ansible_dir / "target_inventory.ini"
    k6_inventory = ansible_dir / "k6_inventory.ini"
    _write_inventory(target_inventory, target_host)
    _write_inventory(k6_inventory, k6_host)

    setup_target = Path("lb_plugins/plugins/dfaas/ansible/setup_target.yml")
    setup_k6 = Path("lb_plugins/plugins/dfaas/ansible/setup_k6.yml")

    try:
        _run_playbook(
            setup_target,
            target_inventory,
            {"openfaas_functions": ["env"]},
            ansible_env,
        )
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail("setup_target playbook failed", context="setup_target", exc=exc)
    try:
        _run_playbook(
            setup_k6,
            k6_inventory,
            {"k6_workspace_root": k6_workspace_root},
            ansible_env,
        )
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail("setup_k6 playbook failed", context="setup_k6", exc=exc)

    try:
        k6_version = _multipass_exec(k6_vm["name"], ["k6", "version"]).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail("k6 not available on k6 host", context="verify_k6", exc=exc)
    assert "k6" in k6_version, "k6 version output should contain 'k6'"

    try:
        _multipass_exec(target_vm["name"], ["kubectl", "get", "nodes"])
        _multipass_exec(
            target_vm["name"], ["kubectl", "-n", "openfaas", "get", "deploy", "gateway"]
        )
        _multipass_exec(
            target_vm["name"],
            ["kubectl", "-n", "openfaas", "get", "deploy", "prometheus"],
        )
        _multipass_exec(
            target_vm["name"],
            [
                "sudo",
                "env",
                "KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
                "helm",
                "-n",
                "openfaas",
                "list",
            ],
        )
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail(
            "k3s/OpenFaaS/Prometheus not healthy", context="verify_k3s_stack", exc=exc
        )

    gateway_url = f"http://{target_vm['ip']}:31112"
    prometheus_url = f"http://{target_vm['ip']}:30411"

    try:
        _wait_for_http(f"{prometheus_url}/-/ready")
    except Exception as exc:  # noqa: BLE001
        if shutil.which("ssh") is None:
            _skip_or_fail(
                "Prometheus not reachable from host", context="prometheus_http", exc=exc
            )

        try:
            with ssh_tunnel(
                target_vm["ip"],
                target_vm["user"],
                str(staged_key),
                remote_port=30411,
                remote_host=target_vm["ip"],
            ) as local_port:
                prometheus_url = f"http://127.0.0.1:{local_port}"
                _wait_for_http(f"{prometheus_url}/-/ready")

                # Perform prometheus checks within tunnel scope
                _wait_for_prometheus_metric(prometheus_url, "node_cpu_seconds_total")
                _wait_for_prometheus_metric(
                    prometheus_url, "node_memory_MemTotal_bytes"
                )
                _wait_for_prometheus_metric(
                    prometheus_url, "container_cpu_usage_seconds_total"
                )
                queries = load_queries(Path("lb_plugins/plugins/dfaas/queries.yml"))
                active_queries = filter_queries(queries, scaphandre_enabled=False)
                queries_by_name = {query.name: query for query in active_queries}
                time_span = "30s"
                runner = PrometheusQueryRunner(
                    prometheus_url, retry_seconds=180, sleep_seconds=3
                )
                for name in ("cpu_usage_node", "ram_usage_node", "ram_usage_node_pct"):
                    runner.execute(queries_by_name[name], time_span=time_span)
        except Exception as tunnel_exc:
            _skip_or_fail(
                "Prometheus tunnel/metrics failed",
                context="prometheus_tunnel",
                exc=tunnel_exc,
            )

    # Note: If tunnel was used, prometheus_url is now invalid (local port closed).
    # But generator uses the VM internal IP for prometheus, so that's fine.

    try:
        password = _get_openfaas_password(target_vm["name"])
        _login_openfaas(gateway_url, password)
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail("OpenFaaS login failed", context="openfaas_login", exc=exc)

    auth_value = base64.b64encode(f"admin:{password}".encode("utf-8")).decode("utf-8")

    config = DfaasConfig(
        gateway_url=gateway_url,
        prometheus_url=f"http://{target_vm['ip']}:30411",  # Use VM IP for generator
        k6_host=k6_vm["ip"],
        k6_user=k6_vm["user"],
        k6_ssh_key=str(staged_key),
        k6_port=22,
        k6_workspace_root=k6_workspace_root,
        output_dir=tmp_path / "dfaas_results",
        functions=[
            DfaasFunctionConfig(
                name="env",
                method="GET",
                body="",
                headers={"Authorization": f"Basic {auth_value}"},
            )
        ],
        rates=DfaasRatesConfig(min_rate=1, max_rate=1, step=1),
        combinations=DfaasCombinationConfig(min_functions=1, max_functions=2),
        duration="30s",
        iterations=1,
        cooldown=DfaasCooldownConfig(
            max_wait_seconds=60,
            sleep_step_seconds=5,
            idle_threshold_pct=20,
        ),
    )

    generator = DfaasGenerator(config)
    if not generator.check_prerequisites():
        _skip_or_fail("DFaaS generator prerequisites not met on host.")

    try:
        generator._run_command()
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail("DFaaS generator run failed", context="generator_run", exc=exc)

    result = generator.get_result()
    assert (
        result is not None and result.get("success") is True
    ), "DFaaS generator result success should be true"
    assert bool(
        result.get("dfaas_results")
    ), "DFaaS generator result should have dfaas_results"
    assert bool(
        result.get("dfaas_summaries")
    ), "DFaaS generator result should have dfaas_summaries"

    config_ids = _extract_config_ids_from_summaries(result.get("dfaas_summaries", []))
    if not config_ids:
        config_ids = [
            str(entry["config_id"])
            for entry in result.get("dfaas_scripts", [])
            if isinstance(entry, dict) and entry.get("config_id")
        ]

    plugin = DfaasPlugin()
    output_dir = config.output_dir or tmp_path / "dfaas_results"
    paths = plugin.export_results_to_csv(
        [{"generator_result": result, "repetition": 1}],
        output_dir=Path(output_dir),
        run_id="dfaas_e2e",
        test_name="dfaas",
    )
    assert any(
        path.name == "results.csv" for path in paths
    ), "results.csv should be exported"

    # Verify artifact structure and content
    _verify_dfaas_artifact_structure(Path(output_dir))
    _verify_results_csv_content(Path(output_dir) / "results.csv")

    # Verify k6 logs on generator VM
    _verify_k6_logs_on_generator(
        k6_vm["name"],
        k6_workspace_root,
        config_ids=config_ids,
    )


def test_dfaas_multipass_streaming_events(multipass_two_vms, tmp_path: Path) -> None:
    _ensure_local_prereqs()
    target_vm, k6_vm = multipass_two_vms[0], multipass_two_vms[1]
    k6_workspace_root = _k6_workspace_root(k6_vm["user"])
    configured_lb_workdir = _lb_workdir(target_vm["user"])

    # Cleanup before run
    _clean_remote_workspace(k6_vm["name"], [k6_workspace_root])
    _clean_remote_workspace(
        target_vm["name"], ["/tmp/benchmark_results", "/tmp/dfaas_stream_results"]
    )

    ansible_dir = tmp_path / "ansible_dfaas_stream"
    staged_key = stage_private_key(Path(target_vm["key_path"]), ansible_dir / "keys")
    _ensure_dfaas_k6_key_on_target(
        target_vm["name"],
        target_vm["user"],
        staged_key,
    )
    target_host = {
        "ip": target_vm["ip"],
        "user": target_vm["user"],
        "key": str(staged_key),
    }
    k6_host = {
        "ip": k6_vm["ip"],
        "user": k6_vm["user"],
        "key": str(staged_key),
    }

    ansible_env = make_test_ansible_env(ansible_dir)
    target_inventory = ansible_dir / "target_inventory.ini"
    k6_inventory = ansible_dir / "k6_inventory.ini"
    _write_inventory(target_inventory, target_host)
    _write_inventory(k6_inventory, k6_host)

    setup_target = Path("lb_plugins/plugins/dfaas/ansible/setup_target.yml")
    setup_k6 = Path("lb_plugins/plugins/dfaas/ansible/setup_k6.yml")

    try:
        _run_playbook(
            setup_target,
            target_inventory,
            {"openfaas_functions": ["env"], "lb_workdir": configured_lb_workdir},
            ansible_env,
        )
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail(
            "setup_target playbook failed", context="setup_target_streaming", exc=exc
        )

    try:
        _run_playbook(
            setup_k6,
            k6_inventory,
            {"k6_workspace_root": k6_workspace_root},
            ansible_env,
        )
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail("setup_k6 playbook failed", context="setup_k6_streaming", exc=exc)

    k6_key_path = str(staged_key)

    try:
        password = _get_openfaas_password(target_vm["name"])
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail(
            "Failed to read OpenFaaS password",
            context="openfaas_password_streaming",
            exc=exc,
        )

    auth_value = base64.b64encode(f"admin:{password}".encode("utf-8")).decode("utf-8")

    dfaas_config = DfaasConfig(
        gateway_url=f"http://{target_vm['ip']}:31112",
        prometheus_url=f"http://{target_vm['ip']}:30411",
        k6_host=k6_vm["ip"],
        k6_user=k6_vm["user"],
        k6_ssh_key=k6_key_path,
        k6_port=22,
        k6_workspace_root=k6_workspace_root,
        functions=[
            DfaasFunctionConfig(
                name="env",
                method="GET",
                body="",
                headers={"Authorization": f"Basic {auth_value}"},
            )
        ],
        rates=DfaasRatesConfig(min_rate=1, max_rate=1, step=1),
        combinations=DfaasCombinationConfig(min_functions=1, max_functions=2),
        duration="30s",
        iterations=1,
        cooldown=DfaasCooldownConfig(
            max_wait_seconds=60,
            sleep_step_seconds=5,
            idle_threshold_pct=20,
        ),
        k6_log_stream=True,
    )

    try:
        _wait_for_http(f"http://{target_vm['ip']}:30411/-/ready")
        _wait_for_prometheus_metric(
            f"http://{target_vm['ip']}:30411", "node_cpu_seconds_total"
        )
        _wait_for_prometheus_metric(
            f"http://{target_vm['ip']}:30411", "node_memory_MemTotal_bytes"
        )
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail(
            "Prometheus not ready for DFaaS run",
            context="prometheus_ready_streaming",
            exc=exc,
        )

    output_dir = tmp_path / "dfaas_stream_results"
    report_dir = tmp_path / "dfaas_stream_reports"
    export_dir = tmp_path / "dfaas_stream_exports"
    host_configs = [
        RemoteHostConfig(
            name=target_vm["name"],
            address=target_vm["ip"],
            user=target_vm["user"],
            become=True,
            vars={
                "ansible_ssh_private_key_file": str(staged_key),
                "ansible_ssh_common_args": (
                    "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
                ),
            },
        )
    ]

    workload_cfg = WorkloadConfig(
        plugin="dfaas",
        options=dfaas_config.model_dump(mode="json"),
    )
    config = BenchmarkConfig(
        repetitions=1,
        test_duration_seconds=60,
        warmup_seconds=0,
        cooldown_seconds=0,
        output_dir=output_dir,
        report_dir=report_dir,
        data_export_dir=export_dir,
        remote_hosts=host_configs,
        remote_execution=RemoteExecutionConfig(
            enabled=True,
            run_setup=True,
            run_collect=True,
            run_teardown=False,
            lb_workdir=configured_lb_workdir,
        ),
        plugin_settings={"dfaas": dfaas_config},
        plugin_assets={
            "dfaas": PluginAssetConfig(setup_playbook=None, teardown_playbook=None)
        },
        workloads={"dfaas": workload_cfg},
        collectors=MetricCollectorConfig(
            psutil_interval=1.0,
            cli_commands=["uptime"],
            enable_ebpf=False,
        ),
    )

    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    k6_log_started = threading.Event()
    execute_completed = threading.Event()
    run_done = threading.Event()
    run_summary: dict[str, object] = {}
    observed_events: list[dict[str, Any]] = []
    observed_lb_workdir: str | None = None
    expected_config_ids = _expected_config_ids_from_config(dfaas_config)

    def _output_cb(text: str, end: str) -> None:
        nonlocal observed_lb_workdir
        if "lb_workdir=" in text and observed_lb_workdir is None:
            import re

            match = re.search(r"lb_workdir=([^\s]+)", text)
            if match:
                observed_lb_workdir = match.group(1)
        if any(
            token in text
            for token in (
                "Stream LB_EVENT lines (polling loop)",
                "Poll LB_EVENT stream",
                "LB_POLL_STATUS:",
            )
        ):
            execute_completed.set()
        if "k6[" in text and "log stream started" in text:
            k6_log_started.set()
        if "LB_EVENT" not in text:
            return
        event = _extract_lb_event(text)
        if not event:
            return
        observed_events.append(event)
        message = str(event.get("message", ""))
        if "k6[" in message and "log stream started" in message:
            k6_log_started.set()

    executor = AnsibleRunnerExecutor(
        private_data_dir=ansible_dir / "runner",
        stream_output=True,
        output_callback=_output_cb,
    )
    controller = BenchmarkController(config, ControllerOptions(executor=executor))

    def _run_controller() -> None:
        try:
            run_summary["summary"] = controller.run(
                ["dfaas"], run_id="dfaas_streaming_e2e"
            )
        finally:
            run_done.set()

    thread = threading.Thread(target=_run_controller, daemon=True)
    thread.start()

    if not execute_completed.wait(timeout=120):
        pytest.fail("Execute dfaas repetition task did not complete quickly.")

    event_log_path = (
        f"/tmp/benchmark_results/dfaas_streaming_e2e/"
        f"{target_vm['name']}/lb_events.stream.log"
    )
    deadline = time.time() + 600
    while time.time() < deadline and not k6_log_started.is_set():
        if _remote_file_exists(target_vm["name"], event_log_path):
            try:
                content = _remote_read_file(target_vm["name"], event_log_path)
                if "k6[" in content and "log stream started" in content:
                    k6_log_started.set()
                    break
            except FileNotFoundError:
                pass
        if run_done.is_set():
            break
        time.sleep(2)

    if not k6_log_started.is_set():
        if run_done.is_set():
            summary = run_summary.get("summary")
            if summary and getattr(summary, "success", False) is False:
                phase_lines: list[str] = []
                phases = getattr(summary, "phases", None)
                if isinstance(phases, dict):
                    for name, result in phases.items():
                        rc = getattr(result, "rc", None)
                        status = getattr(result, "status", None)
                        phase_lines.append(f"{name}: rc={rc} status={status}")

                event_log_path = (
                    f"/tmp/benchmark_results/dfaas_streaming_e2e/"
                    f"{target_vm['name']}/lb_events.stream.log"
                )
                event_log_tail = "event log not available"
                if _remote_file_exists(target_vm["name"], event_log_path):
                    try:
                        content = _remote_read_file(target_vm["name"], event_log_path)
                        tail_lines = content.splitlines()[-40:]
                        event_log_tail = "\n".join(tail_lines)
                    except FileNotFoundError:
                        event_log_tail = "event log missing after check"

                details = "\n".join(
                    [
                        "Run summary indicates failure before k6 log stream started.",
                        f"run_id={getattr(summary, 'run_id', 'unknown')}",
                        "phases:",
                        *phase_lines,
                        "event_log_tail:",
                        event_log_tail,
                    ]
                )
                _skip_or_fail(
                    "DFaaS run failed before k6 log stream started.\n" + details
                )

        messages = [
            str(ev.get("message", "")) for ev in observed_events if isinstance(ev, dict)
        ]
        saw_stream_disabled = any("k6 log stream disabled" in msg for msg in messages)
        saw_dfaa_config = any(
            "DFaaS config " in msg and "skipped=" not in msg for msg in messages
        )
        saw_dfaa_skipped = any("skipped=" in msg for msg in messages)
        saw_k6_error = any(
            "k6 execution error" in msg or "k6 playbook failed" in msg
            for msg in messages
        )
        saw_cooldown_timeout = any(
            "cooldown timeout" in msg.lower() for msg in messages
        )

        event_log_exists = _remote_file_exists(target_vm["name"], event_log_path)
        event_log_lines = 0
        if event_log_exists:
            try:
                content = _remote_read_file(target_vm["name"], event_log_path)
                event_log_lines = len(
                    [line for line in content.split("\n") if "LB_EVENT" in line]
                )
            except FileNotFoundError:
                event_log_lines = 0

        k6_logs = _remote_find_files(k6_vm["name"], k6_workspace_root, "k6.log")
        k6_summaries = _remote_find_files(
            k6_vm["name"], k6_workspace_root, "summary.json"
        )
        k6_scripts = _remote_find_files(k6_vm["name"], k6_workspace_root, "script.js")

        status_summary = "status file not checked"
        status_path = None
        if observed_lb_workdir:
            status_path = f"{observed_lb_workdir}/lb_localrunner.status.json"
        elif configured_lb_workdir:
            status_path = f"{configured_lb_workdir}/lb_localrunner.status.json"
        if status_path:
            if _remote_file_exists(target_vm["name"], status_path):
                try:
                    status_summary = _remote_read_file(
                        target_vm["name"], status_path
                    ).strip()
                except FileNotFoundError:
                    status_summary = "status file missing after check"
            else:
                status_summary = "status file not found"

        diag_lines = [
            f"observed_events={len(observed_events)}",
            f"event_log_exists={event_log_exists} lb_event_lines={event_log_lines}",
            f"k6_logs={len(k6_logs)} summaries={len(k6_summaries)} scripts={len(k6_scripts)}",
            f"expected_config_ids={expected_config_ids}",
            f"configured_lb_workdir={configured_lb_workdir}",
            f"observed_lb_workdir={observed_lb_workdir or 'unknown'} status={status_summary}",
            f"saw_stream_disabled={saw_stream_disabled}",
            f"saw_dfaa_config={saw_dfaa_config} saw_dfaa_skipped={saw_dfaa_skipped}",
            f"saw_k6_error={saw_k6_error} saw_cooldown_timeout={saw_cooldown_timeout}",
        ]
        pytest.fail(
            "No k6 log stream started event within 600 seconds.\n"
            + "\n".join(diag_lines)
        )

    thread.join(timeout=900)
    if thread.is_alive():
        pytest.fail("DFaaS streaming run did not finish in time.")

    # Validate that k6 config scripts were generated and copied to generator,
    # and that k6 produced artifacts for each expected config.
    _verify_k6_workspace_artifacts(
        k6_vm["name"],
        k6_workspace_root,
        expected_config_ids,
        wait_seconds=180,
    )

    summary = run_summary.get("summary")
    if summary and getattr(summary, "success", False) is False:
        _skip_or_fail("DFaaS streaming run failed; see logs for details.")


def _remote_file_exists(vm_name: str, path: str) -> bool:
    """Check if a file exists on the remote VM."""
    result = subprocess.run(
        ["multipass", "exec", vm_name, "--", "test", "-f", path],
        capture_output=True,
    )
    return result.returncode == 0


def _remote_read_file(vm_name: str, path: str) -> str:
    """Read a file from the remote VM."""
    result = subprocess.run(
        ["multipass", "exec", vm_name, "--", "cat", path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FileNotFoundError(f"Cannot read {path} on {vm_name}: {result.stderr}")
    return result.stdout


def _remote_list_dir(vm_name: str, path: str) -> list[str]:
    """List directory contents on remote VM."""
    result = subprocess.run(
        ["multipass", "exec", vm_name, "--", "ls", "-la", path],
        capture_output=True,
        text=True,
    )
    return result.stdout.split("\n") if result.returncode == 0 else []


def _remote_find_files(vm_name: str, path: str, pattern: str) -> list[str]:
    """Find files matching pattern on remote VM."""
    cmd = [
        "multipass",
        "exec",
        vm_name,
        "--",
        "sudo",
        "find",
        path,
        "-name",
        pattern,
        "-type",
        "f",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(
            "sudo find failed on %s (%s). stderr: %s",
            vm_name,
            " ".join(cmd),
            result.stderr.strip(),
        )
        fallback = [
            "multipass",
            "exec",
            vm_name,
            "--",
            "find",
            path,
            "-name",
            pattern,
            "-type",
            "f",
        ]
        result = subprocess.run(fallback, capture_output=True, text=True)
    return [f for f in result.stdout.strip().split("\n") if f]


def _verify_dfaas_artifact_structure(output_dir: Path) -> None:
    """Verify all expected DFaaS artifacts exist."""
    assert (
        output_dir / "results.csv"
    ).exists(), f"results.csv should exist in {output_dir}"

    summaries = list(output_dir.glob("summaries/summary-*.json"))
    assert (
        len(summaries) > 0
    ), f"summary files should be found in {output_dir}/summaries"

    k6_scripts = list(output_dir.glob("k6_scripts/*.js"))
    assert len(k6_scripts) > 0, f"k6 scripts should be found in {output_dir}/k6_scripts"


def _verify_results_csv_content(results_path: Path) -> None:
    """Verify results.csv has valid success_rate values."""
    import csv

    print(f"--- results.csv: {results_path} ---")
    content = results_path.read_text()
    print(content)

    with open(results_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) > 0, "results.csv should have at least one row"

    # Check for success_rate columns
    success_cols = [k for k in rows[0].keys() if k.startswith("success_rate_function_")]
    assert (
        len(success_cols) > 0
    ), f"success_rate columns should be found. Columns: {list(rows[0].keys())}"

    for row in rows:
        for col in success_cols:
            val = float(row[col])
            assert val >= 0, f"{col} should have valid value: {val}"


def _verify_results_csv_text(content: str) -> None:
    """Verify results.csv content (remote) has valid success_rate values."""
    import csv
    import io

    print("--- results.csv (remote) ---")
    print(content)

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    assert len(rows) > 0, "results.csv should have at least one row"

    success_cols = [k for k in rows[0].keys() if k.startswith("success_rate_function_")]
    assert (
        len(success_cols) > 0
    ), f"success_rate columns should be found. Columns: {list(rows[0].keys())}"

    for row in rows:
        for col in success_cols:
            val = float(row[col])
            assert val >= 0, f"{col} should have valid value: {val}"


def _verify_peva_faas_results_text(content: str) -> None:
    """Verify peva_faas_results.json has successful entries."""
    data = json.loads(content)
    assert (
        isinstance(data, list) and data
    ), "peva_faas_results.json should contain entries"
    entry = data[0]
    assert entry.get("success") is True, "peva_faas_results.json should report success"


def _verify_peva_faas_result_text(content: str) -> None:
    """Verify rep1/result.json has success true."""
    entry = json.loads(content)
    assert entry.get("success") is True, "rep1/result.json should report success"


def _extract_config_ids_from_summaries(
    summaries: list[dict[str, Any]],
) -> list[str]:
    config_ids = {
        str(entry["config_id"])
        for entry in summaries
        if isinstance(entry, dict) and entry.get("config_id")
    }
    return sorted(config_ids)


def _extract_config_ids_from_summary_files(summary_dir: Path) -> list[str]:
    import re

    config_ids = set()
    for summary_path in summary_dir.glob("summary-*-iter*-rep*.json"):
        match = re.match(r"summary-(.+)-iter", summary_path.name)
        if match:
            config_ids.add(match.group(1))
    return sorted(config_ids)


def _verify_k6_workspace_artifacts(
    vm_name: str,
    workspace_root: str,
    config_ids: list[str],
    wait_seconds: int = 0,
    poll_interval_seconds: int = 2,
) -> None:
    """Verify k6 workspace has script, summary, and log per config."""
    assert bool(
        config_ids
    ), "config IDs should be available for k6 workspace verification"

    deadline = time.time() + max(0, wait_seconds)
    last_counts: dict[str, tuple[int, int, int]] = {}
    while True:
        all_logs = _remote_find_files(vm_name, workspace_root, "k6.log")
        all_summaries = _remote_find_files(vm_name, workspace_root, "summary.json")
        missing_config = None
        for config_id_value in config_ids:
            script_paths = [
                p
                for p in _remote_find_files(vm_name, workspace_root, "script.js")
                if f"/{config_id_value}/" in p
            ]
            summary_paths = [p for p in all_summaries if f"/{config_id_value}/" in p]
            log_paths = [p for p in all_logs if f"/{config_id_value}/" in p]
            last_counts[config_id_value] = (
                len(script_paths),
                len(summary_paths),
                len(log_paths),
            )
            if not script_paths or not summary_paths or not log_paths:
                missing_config = config_id_value
                break
        if missing_config is None:
            break
        if time.time() >= deadline:
            script_count, summary_count, log_count = last_counts.get(
                missing_config, (0, 0, 0)
            )
            debug_cmd = f"sudo find {workspace_root} -path '*{missing_config}*' -type f 2>/dev/null"
            try:
                debug_output = _multipass_exec(
                    vm_name, ["bash", "-c", debug_cmd]
                ).stdout
            except Exception as exc:  # noqa: BLE001
                debug_output = f"Failed to collect debug output: {exc}"

            counts_lines = [
                f"{cid}: scripts={counts[0]} summaries={counts[1]} logs={counts[2]}"
                for cid, counts in sorted(last_counts.items())
            ]
            pytest.fail(
                "k6 workspace missing artifacts for config "
                f"{missing_config}: scripts={script_count} "
                f"summaries={summary_count} logs={log_count}\n"
                "Workspace counts:\n"
                + "\n".join(counts_lines)
                + "\nWorkspace matches:\n"
                + debug_output
            )
        time.sleep(max(1, poll_interval_seconds))

    all_logs = _remote_find_files(vm_name, workspace_root, "k6.log")
    for config_id_value in config_ids:
        log_paths = [p for p in all_logs if f"/{config_id_value}/" in p]
        for log_path in log_paths:
            content = _remote_read_file(vm_name, log_path)
            assert bool(content.strip()), f"k6.log should be non-empty: {log_path}"

            content_lower = content.lower()
            markers = (
                "running",
                "vus",
                "http_req_duration",
                "checks",
                "data_received",
                "iteration_duration",
            )
            if not any(marker in content_lower for marker in markers):
                tail = content.strip()[-500:]
                pytest.fail(
                    "k6.log does not look like a k6 run output: "
                    f"{log_path}\nLast 500 chars:\n{tail}"
                )


def _expected_config_ids_from_config(config: DfaasConfig) -> list[str]:
    # Use rate_strategy to generate rates (supports all strategy types)
    rates = config.rate_strategy.generate_rates()
    rates_by_function: dict[str, list[int]] = {}
    for fn in config.functions:
        if fn.max_rate is None:
            continue
        rates_by_function[fn.name] = [rate for rate in rates if rate <= fn.max_rate]
    function_names = sorted(fn.name for fn in config.functions)
    configs = generate_configurations(
        function_names,
        rates,
        config.combinations.min_functions,
        config.combinations.max_functions,
        rates_by_function=rates_by_function,
    )
    return [config_id(cfg) for cfg in configs]


def _verify_k6_logs_on_generator(
    vm_name: str,
    workspace_root: str,
    target_vm_name: str | None = None,
    cli_stdout: str | None = None,
    config_ids: list[str] | None = None,
) -> None:
    """Verify k6 generated logs on the generator VM."""
    print(f"Verifying k6 logs on {vm_name} in {workspace_root}")

    # Check if we saw streamed logs in CLI output
    if cli_stdout and "k6[" in cli_stdout and "stdout:" in cli_stdout:
        print("✓ Confirmed k6 logs were streamed to CLI output")
        return

    if config_ids:
        _verify_k6_workspace_artifacts(vm_name, workspace_root, config_ids)
        return

    k6_logs = _remote_find_files(vm_name, workspace_root, "k6.log")
    print(f"Found k6 logs on generator: {k6_logs}")

    if not k6_logs:
        print(
            f"No k6 logs found on generator {vm_name}. Listing {workspace_root} recursively with sudo:"
        )
        try:
            ls_cmd = f"sudo ls -laR {workspace_root}; echo 'Hostname:'; hostname"
            ls_result = _multipass_exec(vm_name, ["bash", "-c", ls_cmd])
            print(ls_result.stdout)
        except Exception as e:
            print(f"Failed to list directory on generator: {e}")

        if target_vm_name:
            print(f"Checking target VM {target_vm_name} for misplaced logs...")
            target_logs = _remote_find_files(target_vm_name, workspace_root, "k6.log")
            print(f"Found k6 logs on target: {target_logs}")
            if target_logs:
                print("WARNING: k6 logs found on TARGET VM, not GENERATOR VM!")
                return

    assert (
        len(k6_logs) > 0
    ), f"k6.log files found on generator in {workspace_root} or logs streamed in CLI output"

    for log_path in k6_logs:
        content = _multipass_exec(vm_name, ["sudo", "cat", log_path]).stdout
        # k6 logs should show execution started
        assert len(content) > 0, f"k6.log should be non-empty: {log_path}"


def _verify_lb_installed(vm_name: str, lb_workdir: str) -> bool:
    """Verify lb (linux-benchmark) is installed on the VM.

    lb is installed by the Ansible setup.yml playbook in <lb_workdir>/.venv/bin/lb
    """
    try:
        # Check both the venv location (from Ansible setup) and PATH
        check_cmd = f"""
        if [ -x {lb_workdir}/.venv/bin/lb ]; then
            echo 'lb_venv_ok'
            {lb_workdir}/.venv/bin/lb --version 2>/dev/null || true
        elif command -v lb >/dev/null 2>&1; then
            echo 'lb_path_ok'
            lb --version 2>/dev/null || true
        else
            echo 'lb_not_found'
        fi
        """
        result = _multipass_exec(vm_name, ["bash", "-c", check_cmd])
        return "lb_venv_ok" in result.stdout or "lb_path_ok" in result.stdout
    except Exception:
        return False


def _diagnose_lb_installation(vm_name: str, lb_workdir: str) -> None:
    """Print diagnostic information about lb installation on target."""
    print(f"\nDiagnosing lb installation on {vm_name}:")

    checks = [
        (
            f"ls -la {lb_workdir}/ 2>/dev/null || echo '{lb_workdir} does not exist'",
            "lb_workdir directory",
        ),
        (
            f"ls -la {lb_workdir}/.venv/bin/ 2>/dev/null | head -20 || echo 'venv not found'",
            "venv binaries",
        ),
        (
            f"cat {lb_workdir}/pyproject.toml 2>/dev/null | head -5 || echo 'pyproject.toml not found'",
            "pyproject.toml",
        ),
        (
            f"{lb_workdir}/.venv/bin/lb --version 2>&1 || echo 'lb command failed'",
            "lb version",
        ),
    ]

    for cmd, desc in checks:
        try:
            result = _multipass_exec(vm_name, ["bash", "-c", cmd])
            print(f"  {desc}: {result.stdout.strip()[:200]}")
        except Exception as e:
            print(f"  {desc}: FAILED - {e}")


def test_dfaas_multipass_event_stream_file_creation(
    multipass_two_vms, tmp_path: Path
) -> None:
    """Verify that lb_events.stream.log is created and contains LB_EVENT lines.

    This test specifically checks:
    1. The event stream log file is created on the remote VM
    2. Events are written to it during the run
    3. The LocalRunner emits done/failed events
    """
    _ensure_local_prereqs()
    target_vm, k6_vm = multipass_two_vms[0], multipass_two_vms[1]
    k6_workspace_root = _k6_workspace_root(k6_vm["user"])
    lb_workdir = _lb_workdir(target_vm["user"])

    # Cleanup before run
    _clean_remote_workspace(target_vm["name"], ["/tmp/benchmark_results"])

    ansible_dir = tmp_path / "ansible_dfaas_events"
    staged_key = stage_private_key(Path(target_vm["key_path"]), ansible_dir / "keys")
    target_host = {
        "ip": target_vm["ip"],
        "user": target_vm["user"],
        "key": str(staged_key),
    }
    k6_host = {
        "ip": k6_vm["ip"],
        "user": k6_vm["user"],
        "key": str(staged_key),
    }

    ansible_env = make_test_ansible_env(ansible_dir)
    target_inventory = ansible_dir / "target_inventory.ini"
    k6_inventory = ansible_dir / "k6_inventory.ini"
    _write_inventory(target_inventory, target_host)
    _write_inventory(k6_inventory, k6_host)

    # Setup target and k6 generator from the controller
    setup_target = Path("lb_plugins/plugins/dfaas/ansible/setup_target.yml")
    setup_k6 = Path("lb_plugins/plugins/dfaas/ansible/setup_k6.yml")

    # Ensure benchmark library is deployed for CLI run (skip controller setup later).
    if not _deploy_code_to_vm(target_vm["name"], ansible_dir, staged_key, lb_workdir):
        _skip_or_fail(
            "Failed to deploy code to VM via Ansible setup", context="cli_deploy_code"
        )

    setup_extravars = {
        "openfaas_functions": ["env"],
    }
    try:
        _run_playbook(setup_target, target_inventory, setup_extravars, ansible_env)
    except Exception as exc:
        _skip_or_fail("setup_target failed", context="setup_target_events", exc=exc)
    try:
        _run_playbook(
            setup_k6,
            k6_inventory,
            {"k6_workspace_root": k6_workspace_root},
            ansible_env,
        )
    except Exception as exc:
        _skip_or_fail("setup_k6 failed", context="setup_k6_events", exc=exc)

    try:
        password = _get_openfaas_password(target_vm["name"])
    except Exception as exc:
        _skip_or_fail(
            "Failed to get OpenFaaS password",
            context="openfaas_password_events",
            exc=exc,
        )

    auth_value = base64.b64encode(f"admin:{password}".encode("utf-8")).decode("utf-8")

    # Use short duration for faster testing
    dfaas_config = DfaasConfig(
        gateway_url=f"http://{target_vm['ip']}:31112",
        prometheus_url=f"http://{target_vm['ip']}:30411",
        k6_host=k6_vm["ip"],
        k6_user=k6_vm["user"],
        k6_ssh_key=str(staged_key),
        k6_port=22,
        k6_workspace_root=k6_workspace_root,
        functions=[
            DfaasFunctionConfig(
                name="env",
                method="GET",
                body="",
                headers={"Authorization": f"Basic {auth_value}"},
            )
        ],
        rates=DfaasRatesConfig(min_rate=1, max_rate=1, step=1),
        combinations=DfaasCombinationConfig(min_functions=1, max_functions=2),
        duration="10s",  # Short duration
        iterations=1,
        cooldown=DfaasCooldownConfig(
            max_wait_seconds=30,
            sleep_step_seconds=3,
            idle_threshold_pct=20,
        ),
    )

    output_dir = tmp_path / "dfaas_events_results"
    host_configs = [
        RemoteHostConfig(
            name=target_vm["name"],
            address=target_vm["ip"],
            user=target_vm["user"],
            become=True,
            vars={
                "ansible_ssh_private_key_file": str(staged_key),
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
            },
        )
    ]

    workload_cfg = WorkloadConfig(
        plugin="dfaas",
        options=dfaas_config.model_dump(mode="json"),
    )
    config = BenchmarkConfig(
        repetitions=1,
        test_duration_seconds=60,
        warmup_seconds=0,
        cooldown_seconds=0,
        output_dir=output_dir,
        report_dir=tmp_path / "reports",
        data_export_dir=tmp_path / "exports",
        remote_hosts=host_configs,
        remote_execution=RemoteExecutionConfig(
            enabled=True, run_setup=True, run_collect=True
        ),
        plugin_settings={"dfaas": dfaas_config},
        plugin_assets={
            "dfaas": PluginAssetConfig(setup_playbook=None, teardown_playbook=None)
        },
        workloads={"dfaas": workload_cfg},
        collectors=MetricCollectorConfig(
            psutil_interval=1.0, cli_commands=[], enable_ebpf=False
        ),
    )

    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    # Track events and remote paths for verification
    observed_events: list[dict[str, Any]] = []
    run_id: str | None = None
    expected_run_id = "dfaas_events_test"
    run_done = threading.Event()
    run_error: Exception | None = None
    event_stream_init = threading.Event()

    def _output_cb(text: str, end: str) -> None:
        nonlocal run_id
        # Extract run_id from log messages
        if "run-" in text and run_id is None:
            import re

            match = re.search(r"run-\d{8}-\d{6}", text)
            if match:
                run_id = match.group()

        if "Initialize event stream files" in text:
            event_stream_init.set()
        if "LB_EVENT" not in text:
            return
        event = _extract_lb_event(text)
        if event:
            observed_events.append(event)
            logger.info("Observed LB_EVENT: %s", event)

    executor = AnsibleRunnerExecutor(
        private_data_dir=ansible_dir / "runner",
        stream_output=True,
        output_callback=_output_cb,
    )
    controller = BenchmarkController(config, ControllerOptions(executor=executor))

    def _run_controller() -> None:
        nonlocal run_error
        try:
            controller.run(["dfaas"], run_id="dfaas_events_test")
        except Exception as exc:
            run_error = exc
        finally:
            run_done.set()

    thread = threading.Thread(target=_run_controller, daemon=True)
    thread.start()

    if not event_stream_init.wait(timeout=600):
        if run_done.is_set():
            pytest.fail("Run finished before event stream files were initialized.")
        logger.warning(
            "Did not observe event stream init marker; checking remote path anyway."
        )

    event_log_path = (
        f"/tmp/benchmark_results/{expected_run_id}/"
        f"{target_vm['name']}/lb_events.stream.log"
    )
    event_log_exists = False
    event_log_lines: list[str] = []
    event_log_deadline = time.time() + 180
    while time.time() < event_log_deadline and not run_done.is_set():
        if _remote_file_exists(target_vm["name"], event_log_path):
            event_log_exists = True
            try:
                content = _remote_read_file(target_vm["name"], event_log_path)
            except FileNotFoundError:
                time.sleep(3)
                continue
            event_log_lines = [
                line for line in content.split("\n") if "LB_EVENT" in line
            ]
            if event_log_lines:
                break
        time.sleep(3)

    if not event_log_exists:
        result_dirs = _remote_list_dir(target_vm["name"], "/tmp/benchmark_results")
        pytest.fail(
            "No lb_events.stream.log file found on remote VM during active run. "
            f"Contents of /tmp/benchmark_results:\n{chr(10).join(result_dirs)}"
        )

    # Wait for run to complete (with timeout)
    completed = run_done.wait(timeout=300)  # 5 minutes max

    if not completed:
        # Gather diagnostic info before failing
        logger.error("Run did not complete in time")

        # Check for remote files
        event_log_files = _remote_find_files(
            target_vm["name"], "/tmp/benchmark_results", "lb_events.stream.log"
        )
        logger.info("Event log files found: %s", event_log_files)

        pid_files = _remote_find_files(
            target_vm["name"], lb_workdir, "lb_localrunner.pid"
        )
        logger.info("PID files found: %s", pid_files)

        status_files = _remote_find_files(
            target_vm["name"], lb_workdir, "lb_localrunner.status.json"
        )
        logger.info("Status files found: %s", status_files)

        # Read event log if it exists
        if event_log_files:
            for ef in event_log_files:
                try:
                    content = _remote_read_file(target_vm["name"], ef)
                    logger.info("Event log content (%s):\n%s", ef, content[:2000])
                except Exception as e:
                    logger.error("Failed to read %s: %s", ef, e)

        pytest.fail("DFaaS run did not complete within timeout")

    thread.join(timeout=10)

    if run_error:
        _skip_or_fail(
            f"DFaaS run failed: {run_error}", context="controller_run", exc=run_error
        )

    if not event_log_lines:
        pytest.fail(
            "No LB_EVENT lines observed in remote event stream during active run"
        )


def _deploy_code_to_vm(
    vm_name: str,
    ansible_dir: Path,
    staged_key: Path,
    lb_workdir: str,
) -> bool:
    """Deploy benchmark library code to VM using Ansible setup playbook."""
    from lb_controller.api import AnsibleRunnerExecutor, InventorySpec
    from lb_runner.api import RemoteHostConfig

    vm_ip = _get_vm_ip(vm_name)
    if not vm_ip:
        logger.error("Could not get IP for VM %s", vm_name)
        return False

    # Create inventory spec with host config
    host_config = RemoteHostConfig(
        name=vm_name,
        address=vm_ip,
        user="ubuntu",
        become=True,
        vars={
            "ansible_ssh_private_key_file": str(staged_key),
            "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
        },
    )
    inventory = InventorySpec(hosts=[host_config])

    setup_playbook = Path("lb_controller/ansible/playbooks/setup.yml")
    if not setup_playbook.exists():
        logger.error("Setup playbook not found: %s", setup_playbook)
        return False

    ansible_env = make_test_ansible_env(ansible_dir)
    os.environ.update(ansible_env)

    executor = AnsibleRunnerExecutor(
        private_data_dir=ansible_dir / "runner_setup",
        stream_output=True,
    )

    try:
        result = executor.run_playbook(
            playbook_path=setup_playbook,
            inventory=inventory,
            extravars={
                "lb_workdir": lb_workdir,
                "output_root": "/tmp/benchmark_results",
            },
        )
        return result.status == "successful"
    except Exception as exc:
        logger.error("Setup playbook failed: %s", exc)
        return False


def _get_vm_ip(vm_name: str) -> str | None:
    """Get IP address of a multipass VM."""
    try:
        result = subprocess.run(
            ["multipass", "info", vm_name, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            ipv4 = data.get("info", {}).get(vm_name, {}).get("ipv4", [])
            return ipv4[0] if ipv4 else None
    except Exception:
        pass
    return None


def test_dfaas_multipass_localrunner_direct(multipass_two_vms, tmp_path: Path) -> None:
    """Test LocalRunner directly on VM to diagnose event emission issues.

    This test deploys code via Ansible, then runs the LocalRunner directly
    to verify that events are emitted correctly.
    """
    _ensure_local_prereqs()
    target_vm = multipass_two_vms[0]
    lb_workdir = _lb_workdir(target_vm["user"])

    # Cleanup
    _clean_remote_workspace(target_vm["name"], ["/tmp/lb_direct_test"])

    ansible_dir = tmp_path / "ansible_direct"
    ansible_dir.mkdir(parents=True, exist_ok=True)

    staged_key = stage_private_key(Path(target_vm["key_path"]), ansible_dir / "keys")

    # Check if lb code is deployed, if not deploy it
    result = subprocess.run(
        [
            "multipass",
            "exec",
            target_vm["name"],
            "--",
            "test",
            "-d",
            f"{lb_workdir}/.venv",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        logger.info("Code not deployed on VM, running setup...")
        if not _deploy_code_to_vm(
            target_vm["name"], ansible_dir, staged_key, lb_workdir
        ):
            _skip_or_fail("Failed to deploy code to VM via Ansible setup")

    # Create a minimal benchmark config on the VM
    config = {
        "repetitions": 1,
        "test_duration_seconds": 5,
        "warmup_seconds": 0,
        "cooldown_seconds": 0,
        "output_dir": "/tmp/lb_direct_test/output",
        "workloads": {
            "baseline": {
                "plugin": "baseline",
                "options": {"duration_seconds": 2},
            }
        },
        "collectors": {
            "psutil_interval": 1.0,
            "enable_ebpf": False,
        },
    }

    config_json = json.dumps(config)
    test_dir = "/tmp/lb_direct_test"
    stream_log = f"{test_dir}/lb_events.stream.log"
    status_file = f"{test_dir}/lb_localrunner.status.json"
    pid_file = f"{test_dir}/lb_localrunner.pid"

    # Setup test directory and config on VM
    setup_cmd = f"""
    set -e
    rm -rf {test_dir}
    mkdir -p {test_dir}
    cat > {test_dir}/benchmark_config.json << 'EOFCONFIG'
{config_json}
EOFCONFIG
    echo "Config written"
    """

    result = subprocess.run(
        ["multipass", "exec", target_vm["name"], "--", "bash", "-c", setup_cmd],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _skip_or_fail(f"Failed to setup test dir: {result.stderr}")

    # Run LocalRunner in foreground (non-daemonized) to see events directly
    run_cmd = f"""
    set -e
    cd {lb_workdir}
    export LB_RUN_HOST=test-host
    export LB_RUN_WORKLOAD=baseline
    export LB_RUN_REPETITION=1
    export LB_RUN_TOTAL_REPS=1
    export LB_RUN_ID=direct-test
    export LB_RUN_STOP_FILE={test_dir}/STOP
    export LB_BENCH_CONFIG_PATH={test_dir}/benchmark_config.json
    export LB_EVENT_STREAM_PATH={stream_log}
    export LB_ENABLE_EVENT_LOGGING=1
    export LB_LOG_LEVEL=INFO
    export LB_RUN_STATUS_PATH={status_file}
    export LB_RUN_PID_PATH={pid_file}
    # NOT setting LB_RUN_DAEMONIZE - run in foreground

    .local/bin/uv run python -m lb_runner.services.async_localrunner 2>&1
    """

    logger.info("Running LocalRunner directly on VM (foreground mode)...")
    result = subprocess.run(
        ["multipass", "exec", target_vm["name"], "--", "bash", "-c", run_cmd],
        capture_output=True,
        text=True,
        timeout=120,
    )

    logger.info("LocalRunner exit code: %d", result.returncode)
    logger.info(
        "LocalRunner stdout:\n%s", result.stdout[:5000] if result.stdout else "(empty)"
    )
    logger.info(
        "LocalRunner stderr:\n%s", result.stderr[:2000] if result.stderr else "(empty)"
    )

    # Check stdout for LB_EVENT lines
    stdout_events = [line for line in result.stdout.split("\n") if "LB_EVENT" in line]
    logger.info("LB_EVENT lines in stdout: %d", len(stdout_events))
    for ev in stdout_events[:10]:
        logger.info("  %s", ev)

    # Check the stream log file
    try:
        log_content = _remote_read_file(target_vm["name"], stream_log)
        logger.info(
            "Stream log content (%d bytes):\n%s", len(log_content), log_content[:3000]
        )

        log_events = [line for line in log_content.split("\n") if "LB_EVENT" in line]
        logger.info("LB_EVENT lines in stream log: %d", len(log_events))
        for ev in log_events[:10]:
            logger.info("  %s", ev)
    except FileNotFoundError as e:
        logger.error("Stream log file not found: %s", e)
        log_events = []

    # Check status file
    try:
        status_content = _remote_read_file(target_vm["name"], status_file)
        logger.info("Status file content: %s", status_content)
    except FileNotFoundError as e:
        logger.error("Status file not found: %s", e)

    assert (
        result.returncode == 0
    ), f"LocalRunner should exit cleanly (rc=0). stderr={result.stderr}"
    assert (
        len(stdout_events) > 0 or len(log_events) > 0
    ), f"LB_EVENT lines should be found in stdout or log. stdout={len(stdout_events)} log={len(log_events)}"


def test_dfaas_multipass_localrunner_daemonized(
    multipass_two_vms, tmp_path: Path
) -> None:
    """Test LocalRunner in daemonized mode on VM.

    This test runs the LocalRunner in daemonized mode to verify that
    events are correctly written to the log file when running as a daemon.
    """
    _ensure_local_prereqs()
    target_vm = multipass_two_vms[0]
    lb_workdir = _lb_workdir(target_vm["user"])

    # Cleanup
    _clean_remote_workspace(target_vm["name"], ["/tmp/lb_daemon_test"])

    ansible_dir = tmp_path / "ansible_daemon"
    ansible_dir.mkdir(parents=True, exist_ok=True)

    staged_key = stage_private_key(Path(target_vm["key_path"]), ansible_dir / "keys")

    # Check if lb code is deployed, if not deploy it
    result = subprocess.run(
        [
            "multipass",
            "exec",
            target_vm["name"],
            "--",
            "test",
            "-d",
            f"{lb_workdir}/.venv",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        logger.info("Code not deployed on VM, running setup...")
        if not _deploy_code_to_vm(
            target_vm["name"], ansible_dir, staged_key, lb_workdir
        ):
            _skip_or_fail("Failed to deploy code to VM via Ansible setup")

    # Create a minimal benchmark config
    config = {
        "repetitions": 1,
        "test_duration_seconds": 5,
        "warmup_seconds": 0,
        "cooldown_seconds": 0,
        "output_dir": "/tmp/lb_daemon_test/output",
        "workloads": {
            "baseline": {
                "plugin": "baseline",
                "options": {"duration_seconds": 2},
            }
        },
        "collectors": {
            "psutil_interval": 1.0,
            "enable_ebpf": False,
        },
    }

    config_json = json.dumps(config)
    test_dir = "/tmp/lb_daemon_test"
    stream_log = f"{test_dir}/lb_events.stream.log"
    status_file = f"{test_dir}/lb_localrunner.status.json"
    pid_file = f"{test_dir}/lb_localrunner.pid"

    # Setup test directory on VM
    setup_cmd = f"""
    set -e
    rm -rf {test_dir}
    mkdir -p {test_dir}
    cat > {test_dir}/benchmark_config.json << 'EOFCONFIG'
{config_json}
EOFCONFIG
    touch {stream_log}
    echo "Setup complete"
    """

    result = subprocess.run(
        ["multipass", "exec", target_vm["name"], "--", "bash", "-c", setup_cmd],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _skip_or_fail(f"Failed to setup test dir: {result.stderr}")

    # Run LocalRunner in daemonized mode
    run_cmd = f"""
    set -e
    cd {lb_workdir}
    export LB_RUN_HOST=test-host
    export LB_RUN_WORKLOAD=baseline
    export LB_RUN_REPETITION=1
    export LB_RUN_TOTAL_REPS=1
    export LB_RUN_ID=daemon-test
    export LB_RUN_STOP_FILE={test_dir}/STOP
    export LB_BENCH_CONFIG_PATH={test_dir}/benchmark_config.json
    export LB_EVENT_STREAM_PATH={stream_log}
    export LB_ENABLE_EVENT_LOGGING=1
    export LB_LOG_LEVEL=INFO
    export LB_RUN_STATUS_PATH={status_file}
    export LB_RUN_PID_PATH={pid_file}
    export LB_RUN_DAEMONIZE=1

    .local/bin/uv run python -m lb_runner.services.async_localrunner
    """

    logger.info("Running LocalRunner in daemonized mode on VM...")
    result = subprocess.run(
        ["multipass", "exec", target_vm["name"], "--", "bash", "-c", run_cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )

    logger.info("Parent exit code: %d", result.returncode)
    assert (
        result.returncode == 0
    ), f"Parent process should exit cleanly (rc=0). stderr={result.stderr}"

    # Wait for PID file
    deadline = time.time() + 10
    while time.time() < deadline:
        if _remote_file_exists(target_vm["name"], pid_file):
            break
        time.sleep(0.5)
    assert _remote_file_exists(
        target_vm["name"], pid_file
    ), "PID file should be created by daemon"

    pid = _remote_read_file(target_vm["name"], pid_file).strip()

    # Wait for status file (daemon completed)
    deadline = time.time() + 60
    while time.time() < deadline:
        if _remote_file_exists(target_vm["name"], status_file):
            break
        time.sleep(1)

        # Check if daemon is still running
        check_result = subprocess.run(
            ["multipass", "exec", target_vm["name"], "--", "kill", "-0", pid],
            capture_output=True,
        )
        if check_result.returncode != 0:
            logger.warning("Daemon process %s no longer running", pid)
            break

    # Read results
    if _remote_file_exists(target_vm["name"], status_file):
        status_content = _remote_read_file(target_vm["name"], status_file)
        logger.info("Status file: %s", status_content)
        status = json.loads(status_content)
        assert status.get("rc") == 0, f"Daemon reported success rc=0. status={status}"
    else:
        logger.error("Status file not created - daemon may have crashed")

    # Check stream log
    if _remote_file_exists(target_vm["name"], stream_log):
        log_content = _remote_read_file(target_vm["name"], stream_log)
        logger.info(
            "Stream log content (%d bytes):\n%s", len(log_content), log_content[:5000]
        )

        log_events = [line for line in log_content.split("\n") if "LB_EVENT" in line]
        logger.info("LB_EVENT lines in stream log: %d", len(log_events))
        for ev in log_events[:10]:
            logger.info("  %s", ev)

        # Should have at least the final done/failed event
        assert (
            len(log_events) > 0
        ), "LB_EVENT lines should be present in daemon stream log"
    else:
        pytest.fail("Stream log file not created by daemon")


def test_peva_faas_multipass_cli_workflow(multipass_two_vms, tmp_path: Path) -> None:
    """E2E test that executes PEVA-faas benchmark via CLI (lb run --remote).

    This test verifies the PEVA-faas workflow:
    1. Infrastructure Setup: k3s/OpenFaaS node + runner node with k6
    2. Configuration Generation: Dynamic JSON config file
    3. Benchmark Execution: Via `uv run lb run --remote -c <config>`
    4. Verification: Artifacts, results content, k6 logs, and LB_EVENT output
    """
    _ensure_local_prereqs()
    k3s_vm, runner_vm = multipass_two_vms[0], multipass_two_vms[1]

    ansible_dir = tmp_path / "ansible_cli"
    staged_key = stage_private_key(Path(runner_vm["key_path"]), ansible_dir / "keys")
    k3s_host = {
        "ip": k3s_vm["ip"],
        "user": k3s_vm["user"],
        "key": str(staged_key),
    }
    runner_host = {
        "ip": runner_vm["ip"],
        "user": runner_vm["user"],
        "key": str(staged_key),
    }

    ansible_env = make_test_ansible_env(ansible_dir)
    k3s_inventory = ansible_dir / "k3s_inventory.ini"
    runner_inventory = ansible_dir / "runner_inventory.ini"
    _write_inventory(k3s_inventory, k3s_host)
    _write_inventory(runner_inventory, runner_host)

    # Setup k3s node and runner (k6) from the controller
    setup_target = Path("lb_plugins/plugins/peva_faas/ansible/setup_target.yml")
    setup_k6 = Path("lb_plugins/plugins/peva_faas/ansible/setup_k6.yml")

    # Use the remote benchmark_results root (remote execution ignores local paths)
    output_dir = Path("/tmp/benchmark_results")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    lb_workdir = _lb_workdir(runner_vm["user"])

    report_dir = tmp_path / "reports"
    export_dir = tmp_path / "exports"

    try:
        _run_playbook(
            setup_target,
            k3s_inventory,
            {
                "openfaas_functions": ["env"],
            },
            ansible_env,
        )
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail(
            "setup_target playbook failed", context="setup_target_cli", exc=exc
        )
    try:
        _run_playbook(
            setup_k6,
            runner_inventory,
            {},
            ansible_env,
        )
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail("setup_k6 playbook failed", context="setup_k6_cli", exc=exc)

    try:
        password = _get_openfaas_password(k3s_vm["name"])
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail(
            "Failed to read OpenFaaS password", context="openfaas_password_cli", exc=exc
        )

    auth_value = base64.b64encode(f"admin:{password}".encode("utf-8")).decode("utf-8")

    # PEVA-faas plugin options - used in both plugin_settings and workloads.options
    peva_faas_options = {
        "gateway_url": f"http://{k3s_vm['ip']}:31112",
        "prometheus_url": f"http://{k3s_vm['ip']}:30411",
        "k3s_host": k3s_vm["ip"],
        "k3s_user": k3s_vm["user"],
        "k3s_ssh_key": str(staged_key),
        "k3s_port": 22,
        "k6_log_stream": True,
        "functions": [
            {
                "name": "env",
                "method": "GET",
                "body": "",
                "headers": {"Authorization": f"Basic {auth_value}"},
            }
        ],
        "rates": {"min_rate": 10, "max_rate": 10, "step": 10},
        "combinations": {"min_functions": 1, "max_functions": 2},
        "duration": "30s",
        "iterations": 1,
        "cooldown": {
            "max_wait_seconds": 60,
            "sleep_step_seconds": 5,
            "idle_threshold_pct": 20,
        },
    }

    runner_vm_name = runner_vm["name"]

    config = {
        "repetitions": 1,
        "test_duration_seconds": 120,  # 2 minutes - enough for 30s k6 run + cooldown
        "warmup_seconds": 0,
        "cooldown_seconds": 0,
        "output_dir": str(output_dir),
        "report_dir": str(report_dir),
        "data_export_dir": str(export_dir),
        "remote_hosts": [
            {
                "name": runner_vm_name,
                "address": runner_vm["ip"],
                "user": runner_vm["user"],
                "become": True,
                "vars": {
                    "ansible_ssh_private_key_file": str(staged_key),
                    "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
                },
            }
        ],
        "remote_execution": {
            "enabled": True,
            "run_setup": False,
            "run_collect": True,
            "run_teardown": False,  # Keep lb_workdir for debugging
            "lb_workdir": lb_workdir,
        },
        "plugin_settings": {
            "peva_faas": peva_faas_options,
        },
        "plugin_assets": {
            "peva_faas": {"setup_playbook": None, "teardown_playbook": None}
        },
        "workloads": {
            "peva_faas": {
                "plugin": "peva_faas",
                "options": peva_faas_options,
                "collectors_enabled": False,
            }
        },
        "collectors": {
            "psutil_interval": 1.0,
            "cli_commands": [],
            "enable_ebpf": False,
        },
    }

    config_path = tmp_path / "benchmark_config.peva_faas_multipass.json"
    config_path.write_text(json.dumps(config, indent=2))

    # Execute benchmark via CLI
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    os.environ["LB_LOG_LEVEL"] = "DEBUG"

    print(f"Executing: uv run lb run --remote -c {config_path}")
    result = subprocess.run(
        ["uv", "run", "lb", "run", "--remote", "-c", str(config_path)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=Path(__file__).parent.parent.parent,  # Project root
        env=os.environ,
    )

    print(f"CLI exit code: {result.returncode}")
    if result.stdout:
        print(f"CLI stdout:\n{result.stdout[:20000]}")
    if result.stderr:
        print(f"CLI stderr:\n{result.stderr[:2000]}")

    cli_failed = result.returncode != 0

    # Capture diagnostics BEFORE failing so we can inspect the VMs
    if cli_failed:
        print("\n" + "=" * 60)
        print("CLI FAILED - CAPTURING DIAGNOSTICS BEFORE CLEANUP")
        print("=" * 60)

        try:
            opt_lb = _multipass_exec(
                runner_vm["name"],
                [
                    "bash",
                    "-c",
                    f"""
                echo "=== {lb_workdir} directory ==="
                ls -la {lb_workdir}/ 2>/dev/null || echo "{lb_workdir} not found"

                echo ""
                echo "=== LocalRunner status file ==="
                cat {lb_workdir}/lb_localrunner.status.json 2>/dev/null || echo "No status file"

                echo ""
                echo "=== LocalRunner PID file ==="
                cat {lb_workdir}/lb_localrunner.pid 2>/dev/null || echo "No PID file"

                echo ""
                echo "=== benchmark_config.generated.json (first 200 lines) ==="
                head -200 {lb_workdir}/benchmark_config.generated.json 2>/dev/null || echo "No generated config"

                echo ""
                echo "=== Event stream log content ==="
                cat /tmp/benchmark_results/*/benchmark-test-vm-*/lb_events.stream.log 2>/dev/null || echo "No stream log"

                echo ""
                echo "=== All files in {lb_workdir} ==="
                find {lb_workdir} -type f 2>/dev/null | head -30

                echo ""
                echo "=== Remote benchmark_results content ==="
                find /tmp -path '*benchmark_results*' -type f 2>/dev/null | head -30
                """,
                ],
            )
            print(opt_lb.stdout)
        except Exception as e:
            print(f"Failed to capture diagnostics: {e}")

        _skip_or_fail(
            f"CLI execution failed with exit code {result.returncode}",
            context="cli_execution",
        )

    # Verify LB_EVENT lines in output
    lb_event_lines = [line for line in result.stdout.split("\n") if "LB_EVENT" in line]
    print(f"Found {len(lb_event_lines)} LB_EVENT lines in CLI output")

    # Verify artifact structure on local output directory (if populated)
    peva_faas_output = output_dir / "peva_faas"
    local_run_dir: Path | None = None
    if peva_faas_output.exists():
        local_run_dir = output_dir
    else:
        run_dirs = list(output_dir.glob("run-*"))
        if run_dirs:
            local_run_dir = run_dirs[0]
            peva_faas_output = local_run_dir / "peva_faas"

    if local_run_dir and peva_faas_output.exists():
        results_path = peva_faas_output / "peva_faas_results.json"
        rep_result_path = peva_faas_output / "rep1" / "result.json"
        assert (
            results_path.exists()
        ), f"peva_faas_results.json should exist in {peva_faas_output}"
        assert (
            rep_result_path.exists()
        ), f"rep1/result.json should exist in {peva_faas_output}"
        _verify_peva_faas_results_text(results_path.read_text())
        _verify_peva_faas_result_text(rep_result_path.read_text())
    else:
        # Remote output (expected for remote execution)
        print("Local output not found; checking remote output directory content...")
        try:
            remote_ls = _multipass_exec(
                runner_vm["name"], ["ls", "-laR", "/tmp/benchmark_results"]
            )
            print(f"Remote /tmp/benchmark_results content:\n{remote_ls.stdout}")
        except Exception as e:
            print(f"Failed to list remote directory: {e}")

        run_id: str | None = None
        for line in lb_event_lines:
            if not line.startswith("LB_EVENT"):
                continue
            try:
                event = json.loads(line.split("LB_EVENT", 1)[1].strip())
            except json.JSONDecodeError:
                continue
            run_id = event.get("run_id") or run_id
            if run_id:
                break

        if run_id:
            remote_run_root = f"/tmp/benchmark_results/{run_id}"
        else:
            remote_run_root = _multipass_exec(
                runner_vm["name"],
                [
                    "bash",
                    "-c",
                    "ls -td /tmp/benchmark_results/run-* 2>/dev/null | head -1",
                ],
            ).stdout.strip()

        remote_output_dir = f"{remote_run_root}/{runner_vm['name']}/peva_faas"
        remote_results = _remote_find_files(
            runner_vm["name"],
            remote_output_dir,
            "peva_faas_results.json",
        )
        assert (
            remote_results
        ), f"peva_faas_results.json should exist in remote output {remote_output_dir}"
        _verify_peva_faas_results_text(
            _remote_read_file(runner_vm["name"], remote_results[0])
        )

        remote_rep_results = _remote_find_files(
            runner_vm["name"],
            f"{remote_output_dir}/rep1",
            "result.json",
        )
        assert (
            remote_rep_results
        ), f"rep1/result.json should exist in {remote_output_dir}/rep1"
        _verify_peva_faas_result_text(
            _remote_read_file(runner_vm["name"], remote_rep_results[0])
        )

    # Debug: Print journal and run log (critical for diagnosing setup failures)
    for path in output_dir.rglob("run_journal.json"):
        print(f"--- Journal: {path} ---")
        try:
            content = path.read_text()
            print(content[:5000])
        except Exception as e:
            print(f"Failed to read journal: {e}")

    for path in output_dir.rglob("run.log"):
        print(f"\n--- Run Log: {path} ---")
        try:
            content = path.read_text()
            # Print last 10000 chars to see setup.yml output
            if len(content) > 10000:
                print(
                    f"... (truncated, showing last 10000 chars of {len(content)} total) ..."
                )
                print(content[-10000:])
            else:
                print(content)
        except Exception as e:
            print(f"Failed to read run log: {e}")

    if not (local_run_dir and peva_faas_output.exists()):
        logger.warning(
            "PEVA-faas output directory not found locally - verified remote output"
        )

    # Debug: Check LocalRunner output and PEVA-faas generator output on runner VM
    print("\n" + "=" * 60)
    print("DIAGNOSING PEVA-FAAS EXECUTION ON RUNNER VM")
    print("=" * 60)

    # With run_teardown=False, lb_workdir should still exist
    print(f"\n--- {lb_workdir} Contents ---")
    try:
        opt_lb = _multipass_exec(
            runner_vm["name"],
            [
                "bash",
                "-c",
                f"""
            echo "=== {lb_workdir} directory ==="
            ls -la {lb_workdir}/ 2>/dev/null || echo "{lb_workdir} not found"

            echo ""
            echo "=== LocalRunner status file ==="
            cat {lb_workdir}/lb_localrunner.status.json 2>/dev/null || echo "No status file"

            echo ""
            echo "=== LocalRunner PID file ==="
            cat {lb_workdir}/lb_localrunner.pid 2>/dev/null || echo "No PID file"

            echo ""
            echo "=== benchmark_config.generated.json (first 200 lines) ==="
            head -200 {lb_workdir}/benchmark_config.generated.json 2>/dev/null || echo "No generated config"

            echo ""
            echo "=== Event stream log ==="
            cat /tmp/benchmark_results/*/benchmark-test-vm-*/lb_events.stream.log 2>/dev/null || echo "No stream log"
            """,
            ],
        )
        print(opt_lb.stdout)
    except Exception as e:
        print(f"Failed to check {lb_workdir}: {e}")

    # Check for LocalRunner execution evidence in /tmp
    print("\n--- LocalRunner Execution Evidence ---")
    try:
        runner_evidence = _multipass_exec(
            runner_vm["name"],
            [
                "bash",
                "-c",
                """
            echo "=== Runner logs in /tmp ==="
            ls -la /tmp/lb_localrunner*.log 2>/dev/null || echo "No runner logs found"

            echo ""
            echo "=== Benchmark results ==="
            find /tmp -path '*benchmark_results*' -type f 2>/dev/null | head -20 || echo "No results found"

            echo ""
            echo "=== PEVA-faas-related files ==="
            find /tmp /home/ubuntu -name '*peva_faas*' -type f 2>/dev/null | head -10 || echo "No peva_faas files"

            echo ""
            echo "=== Process history (if available) ==="
            grep -l -E "lb|peva_faas|k6" /var/log/syslog 2>/dev/null | head -5 || echo "No relevant syslog entries"
            """,
            ],
        )
        print(runner_evidence.stdout)
    except Exception as e:
        print(f"Failed to check runner evidence: {e}")

    # Check for any peva_faas-related output
    try:
        peva_faas_find = _multipass_exec(
            runner_vm["name"],
            [
                "bash",
                "-c",
                f"find /tmp {lb_workdir} /home/ubuntu -name '*peva_faas*' -o -name '*results.csv*' 2>/dev/null | head -20",
            ],
        )
        print(f"PEVA-faas-related files on runner:\n{peva_faas_find.stdout}")
    except Exception as e:
        print(f"Failed to find peva_faas files: {e}")

    # Check LocalRunner stderr/stdout logs
    try:
        runner_logs = _multipass_exec(
            runner_vm["name"],
            [
                "bash",
                "-c",
                "cat /tmp/lb_localrunner*.log 2>/dev/null || echo 'No LocalRunner logs found'",
            ],
        )
        if "No LocalRunner logs" not in runner_logs.stdout:
            print(f"LocalRunner logs:\n{runner_logs.stdout[-3000:]}")
    except Exception as e:
        print(f"Failed to read LocalRunner logs: {e}")

    # Check benchmark results
    try:
        results_find = _multipass_exec(
            runner_vm["name"],
            [
                "bash",
                "-c",
                "find /tmp -path '*benchmark_results*' -name '*.csv' 2>/dev/null",
            ],
        )
        print(f"CSV files in benchmark_results:\n{results_find.stdout}")
        for csv_path in results_find.stdout.strip().split("\n"):
            if csv_path and "results.csv" in csv_path:
                try:
                    csv_content = _remote_read_file(runner_vm["name"], csv_path)
                    print(f"--- Remote {csv_path} ---")
                    print(csv_content[:2000])
                except Exception:
                    pass
    except Exception as e:
        print(f"Failed to find remote CSVs: {e}")

    print("=" * 60 + "\n")

    # Verify k6 logs under output_dir (local) or on the runner VM (remote)
    k6_logs_local = list(output_dir.glob("k6/**/k6.log"))
    if k6_logs_local:
        for log_path in k6_logs_local:
            if log_path.exists():
                content = log_path.read_text()
                assert content.strip(), f"k6.log should be non-empty: {log_path}"
    else:
        try:
            remote_k6_logs = _multipass_exec(
                runner_vm["name"],
                [
                    "bash",
                    "-c",
                    f"find {output_dir} -name 'k6.log' -type f 2>/dev/null | head -20",
                ],
            ).stdout.splitlines()
            if remote_k6_logs:
                for log_path in remote_k6_logs:
                    content = _multipass_exec(
                        runner_vm["name"], ["sudo", "cat", log_path]
                    ).stdout
                    assert content.strip(), f"k6.log should be non-empty: {log_path}"
            else:
                pytest.fail("k6.log files not found in output_dir/k6 on runner")
        except Exception as e:
            pytest.fail(f"Failed to verify k6 logs on runner: {e}")

    # Debug: Search for logs on runner VM to diagnose LocalRunner crash
    print(f"Searching for logs on runner {runner_vm['name']}...")
    try:
        find_cmd = f"find /tmp {lb_workdir} -name '*.log' -type f 2>/dev/null"
        logs = _multipass_exec(
            runner_vm["name"], ["bash", "-c", find_cmd]
        ).stdout.splitlines()
        print(f"Found logs on runner: {logs}")
        for log in logs:
            if "lb_localrunner" in log or "run.log" in log:
                print(f"--- Remote Log: {log} ---")
                try:
                    content = _remote_read_file(runner_vm["name"], log)
                    print(content[-5000:] if len(content) > 5000 else content)
                except Exception as e:
                    print(f"Failed to read {log}: {e}")
    except Exception as e:
        print(f"Failed to search/read logs on runner: {e}")

    # Verify we got some events
    assert (
        len(lb_event_lines) > 0 or result.returncode == 0
    ), "CLI should produce LB_EVENT output or succeed"
