from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit_plugins]

# Variables required by tasks/install_k6.yml
K6_REQUIRED_VARS = {
    "k6_workspace_root",
    "k6_keyring_path",
    "k6_keyserver",
    "k6_key_fingerprint",
    "k6_key_url",
    "k6_repo",
    "k6_tarball_url",
    "k6_tarball_url_fallback",
    "k6_extract_dir",
}

# Variables required by tasks/setup_target_tasks.yml
TARGET_REQUIRED_VARS = {
    "k3s_version",
    "k3s_install_exec",
    "openfaas_namespace",
    "openfaas_fn_namespace",
    "openfaas_gateway_node_port",
    "prometheus_namespace",
    "prometheus_node_port",
    "prometheus_manifests_dir",
}


def _get_ansible_dir() -> Path:
    """Get the DFaaS ansible directory path."""
    return (
        Path(__file__).resolve().parents[4]
        / "lb_plugins"
        / "plugins"
        / "dfaas"
        / "ansible"
    )


def _load_playbook(name: str) -> list[dict]:
    repo_root = Path(__file__).resolve().parents[4]
    path = repo_root / "lb_plugins" / "plugins" / "dfaas" / "ansible" / name
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, list)
    assert data
    return data


def _find_apt_tasks(tasks: list[dict], name: str) -> bool:
    """Recursively find apt tasks with given package name, including inside blocks."""
    for task in tasks:
        # Check direct apt task
        apt_config = task.get("ansible.builtin.apt", {})
        if apt_config.get("name") == name:
            return True
        # Check if name is in a list of packages
        if isinstance(apt_config.get("name"), list) and name in apt_config.get("name"):
            return True
        # Check inside block structures
        if "block" in task:
            if _find_apt_tasks(task["block"], name):
                return True
        # Check inside rescue structures
        if "rescue" in task:
            if _find_apt_tasks(task["rescue"], name):
                return True
    return False


def _find_file_tasks(
    tasks: list[dict],
    *,
    path_contains: str | None = None,
    mode: str | None = None,
) -> bool:
    """Recursively find file tasks with matching path and mode."""
    for task in tasks:
        file_cfg = task.get("ansible.builtin.file", {})
        if file_cfg:
            path_value = str(file_cfg.get("path", ""))
            mode_value = str(file_cfg.get("mode", ""))
            if path_contains and path_contains not in path_value:
                pass
            elif mode and mode_value != mode:
                pass
            else:
                return True
        for key in ("block", "rescue", "always"):
            if key in task and _find_file_tasks(
                task[key],
                path_contains=path_contains,
                mode=mode,
            ):
                return True
    return False


def _find_get_url_tasks(tasks: list[dict], url_contains: str | None = None) -> bool:
    """Recursively find get_url tasks with matching URL substring."""
    for task in tasks:
        get_url_cfg = task.get("ansible.builtin.get_url", {})
        if get_url_cfg:
            url_value = str(get_url_cfg.get("url", ""))
            if url_contains is None or url_contains in url_value:
                return True
        for key in ("block", "rescue", "always"):
            if key in task and _find_get_url_tasks(
                task[key], url_contains=url_contains
            ):
                return True
    return False


def _find_command_tasks(tasks: list[dict], needle: str) -> bool:
    """Recursively find command/shell tasks containing the needle."""
    for task in tasks:
        cmd = (
            task.get("ansible.builtin.command")
            or task.get("ansible.builtin.shell")
            or ""
        )
        if needle in str(cmd):
            return True
        for key in ("block", "rescue", "always"):
            if key in task and _find_command_tasks(task[key], needle):
                return True
    return False


def _find_set_fact_tasks(tasks: list[dict], var_name: str) -> bool:
    """Recursively find set_fact tasks containing a variable name."""
    for task in tasks:
        set_fact_cfg = task.get("ansible.builtin.set_fact", {})
        if isinstance(set_fact_cfg, dict) and var_name in set_fact_cfg:
            return True
        for key in ("block", "rescue", "always"):
            if key in task and _find_set_fact_tasks(task[key], var_name):
                return True
    return False


def test_setup_k6_playbook_imports_install_tasks() -> None:
    """Verify setup_k6.yml imports the k6 installation tasks."""
    playbook = _load_playbook("setup_k6.yml")
    tasks = playbook[0]["tasks"]
    # setup_k6.yml now uses import_tasks for modularity
    import_found = any(
        "install_k6.yml" in str(task.get("ansible.builtin.import_tasks", ""))
        for task in tasks
    )
    assert import_found, "setup_k6.yml should import tasks/install_k6.yml"


def test_install_k6_tasks_has_apt_install() -> None:
    """Verify tasks/install_k6.yml contains k6 apt installation."""
    repo_root = Path(__file__).resolve().parents[4]
    path = (
        repo_root
        / "lb_plugins"
        / "plugins"
        / "dfaas"
        / "ansible"
        / "tasks"
        / "install_k6.yml"
    )
    tasks = yaml.safe_load(path.read_text())
    assert isinstance(tasks, list)
    # k6 is installed via apt with ignore_errors, falling back to tarball if APT fails
    assert _find_apt_tasks(
        tasks, "k6"
    ), "k6 apt installation not found in install_k6.yml"


def test_install_k6_tasks_has_key_download_fallback() -> None:
    """Verify k6 key download fallback is present."""
    repo_root = Path(__file__).resolve().parents[4]
    path = (
        repo_root
        / "lb_plugins"
        / "plugins"
        / "dfaas"
        / "ansible"
        / "tasks"
        / "install_k6.yml"
    )
    tasks = yaml.safe_load(path.read_text())
    assert isinstance(tasks, list)
    assert _find_get_url_tasks(tasks, "k6_key_url"), "k6 key download fallback missing"
    assert _find_command_tasks(tasks, "--dearmor"), "k6 key dearmor step missing"


def test_install_k6_tasks_checks_apt_availability() -> None:
    """Verify install_k6.yml checks apt availability before install."""
    repo_root = Path(__file__).resolve().parents[4]
    path = (
        repo_root
        / "lb_plugins"
        / "plugins"
        / "dfaas"
        / "ansible"
        / "tasks"
        / "install_k6.yml"
    )
    tasks = yaml.safe_load(path.read_text())
    assert isinstance(tasks, list)
    assert _find_command_tasks(
        tasks, "apt-cache policy k6"
    ), "k6 apt-cache check missing"
    assert _find_set_fact_tasks(
        tasks, "k6_apt_available"
    ), "k6_apt_available fact missing"
    assert _find_set_fact_tasks(tasks, "k6_apt_failed"), "k6_apt_failed fact missing"


def test_install_k6_tasks_sets_keyring_permissions() -> None:
    """Verify tasks/install_k6.yml ensures the k6 keyring is apt-readable."""
    repo_root = Path(__file__).resolve().parents[4]
    path = (
        repo_root
        / "lb_plugins"
        / "plugins"
        / "dfaas"
        / "ansible"
        / "tasks"
        / "install_k6.yml"
    )
    tasks = yaml.safe_load(path.read_text())
    assert isinstance(tasks, list)
    assert _find_file_tasks(
        tasks,
        path_contains="k6_keyring_path",
        mode="0644",
    ), "k6 keyring permissions step not found in install_k6.yml"


def test_teardown_k6_playbook_has_cleanup() -> None:
    playbook = _load_playbook("teardown_k6.yml")
    tasks = playbook[0]["tasks"]
    assert any(
        task.get("ansible.builtin.file", {}).get("state") == "absent" for task in tasks
    )


def test_setup_target_playbook_has_core_steps() -> None:
    playbook = _load_playbook("setup_target.yml")
    tasks = playbook[0]["tasks"]
    commands = [
        task.get("ansible.builtin.command") or task.get("ansible.builtin.shell") or ""
        for task in tasks
    ]
    assert any("get.k3s.io" in cmd for cmd in commands)
    assert any("helm upgrade --install openfaas" in cmd for cmd in commands)
    assert any("kubectl apply -f" in cmd for cmd in commands)


# ============================================================================
# Variable Definition Tests - Prevent regression of missing variables bug
# ============================================================================


def _load_vars_file(name: str) -> dict:
    """Load a vars file and return its contents as a dict."""
    path = _get_ansible_dir() / "vars" / name
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text())
    return data if isinstance(data, dict) else {}


def _get_play_defined_vars(play: dict) -> set[str]:
    """Extract variable names defined in a play via vars or vars_files."""
    defined = set()

    # Direct vars
    if "vars" in play and isinstance(play["vars"], dict):
        defined.update(play["vars"].keys())

    # vars_files - load and extract keys
    if "vars_files" in play:
        for vf in play["vars_files"]:
            # Handle relative path like "vars/k6.yml"
            if isinstance(vf, str):
                vf_name = vf.split("/")[-1]  # Get filename
                defined.update(_load_vars_file(vf_name).keys())

    return defined


def test_vars_k6_yml_defines_required_variables() -> None:
    """Verify vars/k6.yml defines all variables required by install_k6.yml.

    This test prevents regression of the bug where k6 variables were
    accidentally removed from setup_plugin.yml, causing Ansible failures.
    """
    vars_data = _load_vars_file("k6.yml")
    defined_vars = set(vars_data.keys())

    missing = K6_REQUIRED_VARS - defined_vars
    assert not missing, (
        f"vars/k6.yml is missing required variables: {missing}\n"
        f"These variables are required by tasks/install_k6.yml"
    )


def test_vars_target_yml_defines_required_variables() -> None:
    """Verify vars/target.yml defines all variables required by setup_target_tasks.yml."""
    vars_data = _load_vars_file("target.yml")
    defined_vars = set(vars_data.keys())

    missing = TARGET_REQUIRED_VARS - defined_vars
    assert not missing, (
        f"vars/target.yml is missing required variables: {missing}\n"
        f"These variables are required by tasks/setup_target_tasks.yml"
    )


def test_setup_plugin_yml_has_vars_files_for_k6() -> None:
    """Verify setup_plugin.yml includes vars/k6.yml for the k6 generator play.

    This test prevents regression of the bug where setup_plugin.yml
    imported tasks/install_k6.yml without defining the required variables.
    """
    playbook = _load_playbook("setup_plugin.yml")

    # Find the "Configure K6 Generator" play (not "Register K6 Generator Host from Config")
    k6_play = None
    for play in playbook:
        name = play.get("name", "").lower()
        if "configure" in name and "k6" in name and "generator" in name:
            k6_play = play
            break

    assert k6_play is not None, "Could not find 'Configure K6 Generator' play"

    # Check that it has vars_files including k6.yml
    vars_files = k6_play.get("vars_files", [])
    has_k6_vars = any("k6.yml" in str(vf) for vf in vars_files)

    assert has_k6_vars, (
        "setup_plugin.yml 'Configure K6 Generator' play must include vars/k6.yml\n"
        "Without this, tasks/install_k6.yml will fail due to undefined variables"
    )


def test_setup_plugin_yml_has_vars_files_for_target() -> None:
    """Verify setup_plugin.yml includes vars/target.yml for the target play."""
    playbook = _load_playbook("setup_plugin.yml")

    # Find the "Configure Benchmark Targets" play
    target_play = None
    for play in playbook:
        if (
            "target" in play.get("name", "").lower()
            and "benchmark" in play.get("name", "").lower()
        ):
            target_play = play
            break

    assert target_play is not None, "Could not find 'Configure Benchmark Targets' play"

    # Check that it has vars_files including target.yml
    vars_files = target_play.get("vars_files", [])
    has_target_vars = any("target.yml" in str(vf) for vf in vars_files)

    assert has_target_vars, (
        "setup_plugin.yml 'Configure Benchmark Targets' play must include vars/target.yml\n"
        "Without this, tasks/setup_target_tasks.yml will fail due to undefined variables"
    )
