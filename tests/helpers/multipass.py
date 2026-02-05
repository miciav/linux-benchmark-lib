import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from lb_app.api import TestService


def get_intensity() -> dict:
    """
    Return intensity parameters based on LB_MULTIPASS_FORCE env var.
    Delegates to the shared TestService logic.
    """
    # The service logic includes mapping names like 'stress'/'stress_duration'.
    # The tests expect keys: stress_duration, stress_timeout, dd_count, fio_runtime, fio_size.
    # TestService.get_multipass_intensity returns a superset including these keys.
    return TestService().get_multipass_intensity()


def ensure_ansible_available() -> None:
    """Skip the test when ansible-playbook is not installed."""
    if shutil.which("ansible-playbook") is None:
        import pytest  # Local import to keep test-only dependency localized

        pytest.skip("ansible-playbook not available on this host")


def _multipass_disabled() -> bool:
    raw = os.environ.get("LB_RUN_MULTIPASS_E2E", "").strip().lower()
    return raw in {"0", "false", "no"}


def ensure_multipass_access() -> None:
    """Skip when multipass is not usable (socket permission, service down)."""
    import subprocess
    import pytest  # Local import to keep test-only dependency localized

    if _multipass_disabled():
        pytest.skip("Multipass e2e disabled via LB_RUN_MULTIPASS_E2E=0")
    if shutil.which("multipass") is None:
        pytest.skip("multipass not available on this host")
    try:
        subprocess.run(
            ["multipass", "list"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        pytest.skip(f"multipass not usable ({exc}); skipping integration tests")


def wait_for_multipass_ip(vm_name: str, attempts: int = 0, delay: int = 0) -> str:
    """Poll multipass info until an IPv4 address is available."""
    if attempts <= 0:
        attempts = int(os.environ.get("LB_MULTIPASS_IP_ATTEMPTS", "30"))
    if delay <= 0:
        delay = int(os.environ.get("LB_MULTIPASS_IP_DELAY", "2"))
    for _ in range(attempts):
        proc = subprocess.run(
            ["multipass", "info", vm_name, "--format", "json"],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            info = json.loads(proc.stdout)
            ipv4 = info["info"][vm_name]["ipv4"]
            if ipv4:
                return ipv4[0]
        exec_proc = subprocess.run(
            ["multipass", "exec", vm_name, "--", "bash", "-c", "hostname -I"],
            capture_output=True,
            text=True,
        )
        if exec_proc.returncode == 0:
            candidates = exec_proc.stdout.split()
            for candidate in candidates:
                if "." in candidate:
                    return candidate
        time.sleep(delay)
    raise RuntimeError(f"Failed to retrieve IP for {vm_name}")


def inject_multipass_ssh_key(vm_name: str, pub_key_path: Path) -> None:
    """Copy the public key into the VM authorized_keys."""
    temp_remote = "/home/ubuntu/lb_test_key.pub"
    subprocess.run(
        ["multipass", "transfer", str(pub_key_path), f"{vm_name}:{temp_remote}"],
        check=True,
    )
    subprocess.run(
        [
            "multipass",
            "exec",
            vm_name,
            "--",
            "bash",
            "-c",
            "mkdir -p ~/.ssh "
            "&& cat ~/lb_test_key.pub >> ~/.ssh/authorized_keys "
            "&& chmod 600 ~/.ssh/authorized_keys "
            "&& rm ~/lb_test_key.pub",
        ],
        check=True,
    )


def cleanup_multipass_vm(vm_name: str) -> None:
    """Force-delete a VM and purge cached data."""
    subprocess.run(
        ["multipass", "delete", vm_name, "--purge"],
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["multipass", "purge"], stderr=subprocess.DEVNULL)


def launch_multipass_vm(
    vm_name: str,
    *,
    image_candidates: list[str] | None = None,
    cpus: int | None = None,
    memory: str | None = None,
    disk: str | None = None,
) -> None:
    """Launch a multipass VM with retries and cleanup on failed starts."""
    images = image_candidates or [
        os.environ.get("LB_MULTIPASS_IMAGE", "24.04"),
        os.environ.get("LB_MULTIPASS_FALLBACK_IMAGE", "lts"),
    ]
    retries = int(os.environ.get("LB_MULTIPASS_LAUNCH_RETRIES", "2"))
    delay = int(os.environ.get("LB_MULTIPASS_LAUNCH_DELAY", "5"))
    last_result: subprocess.CompletedProcess[str] | None = None

    for image in images:
        for attempt in range(retries):
            cmd = ["multipass", "launch", "--name", vm_name]
            if cpus is not None:
                cmd.extend(["--cpus", str(cpus)])
            if memory is not None:
                cmd.extend(["--memory", memory])
            if disk is not None:
                cmd.extend(["--disk", disk])
            cmd.append(image)

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return

            last_result = result
            err_text = (result.stderr or result.stdout or "").lower()
            if "already exists" in err_text or "timed out" in err_text:
                cleanup_multipass_vm(vm_name)
            if attempt < retries - 1:
                time.sleep(delay)

        cleanup_multipass_vm(vm_name)

    if last_result is None:
        raise RuntimeError(f"Failed to launch multipass VM {vm_name}")
    raise subprocess.CalledProcessError(
        last_result.returncode,
        last_result.args,
        output=last_result.stdout,
        stderr=last_result.stderr,
    )


def stage_private_key(source_key: Path, target_dir: Path) -> Path:
    """
    Copy the generated SSH private key into a target directory that Ansible will access.

    The staging location avoids macOS folder permissions (e.g., Downloads) and ensures the
    key remains available even if the original is cleaned up during teardown.
    """
    source_key = Path(source_key)
    if not source_key.exists():
        raise FileNotFoundError(f"SSH key not found at {source_key}")

    target_dir.mkdir(parents=True, exist_ok=True)
    staged_key = target_dir / source_key.name
    shutil.copy2(source_key, staged_key)
    staged_key.chmod(0o600)
    return staged_key


def make_test_ansible_env(
    tmp_path: Path, roles_path: Optional[Path] = None
) -> Dict[str, str]:
    """
    Build an Ansible environment that avoids host-level callback plugins.

    Uses the built-in 'default' callback to prevent dependency on community.general.yaml
    and writes a temporary ansible.cfg in the provided tmp_path.
    """
    local_tmp = tmp_path / ".ansible" / "tmp"
    local_tmp.mkdir(parents=True, exist_ok=True)

    cfg_path = tmp_path / "ansible.cfg"
    callback_dir = tmp_path / "callback_plugins"
    callback_dir.mkdir(parents=True, exist_ok=True)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "[defaults]\n"
        "host_key_checking = False\n"
        "retry_files_enabled = False\n"
        "stdout_callback = default\n"
        "timeout = 60\n"
        f"local_tmp = {local_tmp}\n"
        "remote_tmp = /tmp/.ansible\n"
    )

    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(cfg_path)
    env["ANSIBLE_LOCAL_TEMP"] = str(local_tmp)
    env["ANSIBLE_REMOTE_TMP"] = "/tmp/.ansible"
    env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
    env["ANSIBLE_STDOUT_CALLBACK"] = "default"
    env["ANSIBLE_CALLBACK_PLUGINS"] = str(callback_dir)
    env["ANSIBLE_CALLBACKS_ENABLED"] = "default"
    if roles_path:
        env["ANSIBLE_ROLES_PATH"] = str(roles_path)
    return env
