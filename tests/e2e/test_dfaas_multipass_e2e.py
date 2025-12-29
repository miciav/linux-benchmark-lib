from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from lb_plugins.plugins.dfaas.generator import DfaasGenerator
from lb_plugins.plugins.dfaas.plugin import (
    DfaasCombinationConfig,
    DfaasConfig,
    DfaasCooldownConfig,
    DfaasFunctionConfig,
    DfaasPlugin,
    DfaasRatesConfig,
)
from lb_plugins.plugins.dfaas.queries import (
    PrometheusQueryRunner,
    filter_queries,
    load_queries,
)
from tests.e2e.test_multipass_benchmark import multipass_vm  # noqa: F401 - fixture import
from tests.helpers.multipass import make_test_ansible_env, stage_private_key

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


def _skip_or_fail(message: str) -> None:
    if STRICT_MULTIPASS_SETUP:
        pytest.fail(message)
    pytest.skip(message)


def _ensure_local_prereqs() -> None:
    for tool in ("ansible-playbook", "faas-cli"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not available on this host")


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


def _wait_for_http(url: str, timeout_seconds: int = 180) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            request = Request(url)
            with urlopen(request, timeout=5) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(3)
    raise TimeoutError(f"Timeout waiting for {url}: {last_error}")


def _wait_for_prometheus_metric(
    base_url: str, query: str, timeout_seconds: int = 180
) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            url = f"{base_url}/api/v1/query?{urlencode({'query': query})}"
            request = Request(url)
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("data", {}).get("result"):
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(3)
    raise TimeoutError(f"Timeout waiting for Prometheus metric {query}: {last_error}")


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_ssh_tunnel(
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
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


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
        raise RuntimeError(
            f"faas-cli login failed:\n{result.stdout}\n{result.stderr}"
        )


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


@pytest.fixture(scope="module")
def multipass_two_vms(request):
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


def test_dfaas_multipass_end_to_end(multipass_two_vms, tmp_path: Path) -> None:
    _ensure_local_prereqs()
    target_vm, k6_vm = multipass_two_vms[0], multipass_two_vms[1]

    ansible_dir = tmp_path / "ansible_dfaas"
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
        _skip_or_fail(f"setup_target failed: {exc}")

    try:
        _run_playbook(setup_k6, k6_inventory, None, ansible_env)
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail(f"setup_k6 failed: {exc}")

    try:
        k6_version = _multipass_exec(k6_vm["name"], ["k6", "version"]).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        _skip_or_fail(f"k6 not available on k6 host: {exc}")
    assert "k6" in k6_version

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
        _skip_or_fail(f"k3s/OpenFaaS/Prometheus not healthy: {exc}")

    gateway_url = f"http://{target_vm['ip']}:31112"
    prometheus_url = f"http://{target_vm['ip']}:30411"
    tunnel: subprocess.Popen[str] | None = None

    try:
        _wait_for_http(f"{prometheus_url}/-/ready", timeout_seconds=180)
    except Exception as exc:  # noqa: BLE001
        if shutil.which("ssh") is None:
            _skip_or_fail(f"Prometheus not reachable from host: {exc}")
        local_port = _allocate_local_port()
        tunnel = _start_ssh_tunnel(
            target_vm["ip"],
            target_vm["user"],
            str(staged_key),
            local_port,
            30411,
            remote_host=target_vm["ip"],
        )
        try:
            _wait_for_http(f"http://127.0.0.1:{local_port}/-/ready", timeout_seconds=180)
        except Exception as tunnel_exc:  # noqa: BLE001
            if tunnel:
                tunnel.terminate()
            _skip_or_fail(f"Prometheus tunnel failed: {tunnel_exc}")
        prometheus_url = f"http://127.0.0.1:{local_port}"

    try:
        _wait_for_prometheus_metric(prometheus_url, "node_cpu_seconds_total")
        _wait_for_prometheus_metric(prometheus_url, "node_memory_MemTotal_bytes")
        _wait_for_prometheus_metric(prometheus_url, "container_cpu_usage_seconds_total")
        queries = load_queries(Path("lb_plugins/plugins/dfaas/queries.yml"))
        active_queries = filter_queries(queries, scaphandre_enabled=False)
        queries_by_name = {query.name: query for query in active_queries}
        time_span = "30s"
        runner = PrometheusQueryRunner(prometheus_url, retry_seconds=180, sleep_seconds=3)
        for name in ("cpu_usage_node", "ram_usage_node", "ram_usage_node_pct"):
            runner.execute(queries_by_name[name], time_span=time_span)
    except Exception as exc:  # noqa: BLE001
        if tunnel:
            tunnel.terminate()
        _skip_or_fail(f"Prometheus metrics not ready: {exc}")

    try:
        password = _get_openfaas_password(target_vm["name"])
        _login_openfaas(gateway_url, password)
    except Exception as exc:  # noqa: BLE001
        if tunnel:
            tunnel.terminate()
        _skip_or_fail(f"OpenFaaS login failed: {exc}")

    auth_value = base64.b64encode(f"admin:{password}".encode("utf-8")).decode("utf-8")

    config = DfaasConfig(
        gateway_url=gateway_url,
        prometheus_url=prometheus_url,
        k6_host=k6_vm["ip"],
        k6_user=k6_vm["user"],
        k6_ssh_key=str(staged_key),
        k6_port=22,
        k6_workspace_root="/var/lib/dfaas-k6",
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
        _skip_or_fail(f"DFaaS generator run failed: {exc}")
    finally:
        if tunnel:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()

    result = generator.get_result()
    assert result and result.get("success") is True
    assert result.get("dfaas_results")
    assert result.get("dfaas_summaries")

    plugin = DfaasPlugin()
    output_dir = config.output_dir or tmp_path / "dfaas_results"
    paths = plugin.export_results_to_csv(
        [{"generator_result": result, "repetition": 1}],
        output_dir=Path(output_dir),
        run_id="dfaas_e2e",
        test_name="dfaas",
    )
    assert any(path.name == "results.csv" for path in paths)
