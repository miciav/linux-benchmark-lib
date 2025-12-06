import os
import shutil
from pathlib import Path
from typing import Dict, Optional

from linux_benchmark_lib.services.test_service import TestService


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


def make_test_ansible_env(tmp_path: Path, roles_path: Optional[Path] = None) -> Dict[str, str]:
    """
    Build an Ansible environment that avoids host-level callback plugins.

    Uses the built-in 'default' callback to prevent dependency on community.general.yaml
    and writes a temporary ansible.cfg in the provided tmp_path.
    """
    local_tmp = tmp_path / ".ansible" / "tmp"
    local_tmp.mkdir(parents=True, exist_ok=True)

    cfg_path = tmp_path / "ansible.cfg"
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
    env["ANSIBLE_CALLBACK_PLUGINS"] = ""
    if roles_path:
        env["ANSIBLE_ROLES_PATH"] = str(roles_path)
    return env
