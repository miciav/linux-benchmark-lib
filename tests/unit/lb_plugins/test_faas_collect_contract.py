import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit_plugins]

PLUGINS_ROOT = Path(__file__).resolve().parents[3] / "lb_plugins" / "plugins"


def _run_collect_pre(tmp_path: Path, plugin_name: str, k6_host: str) -> dict:
    """Run the plugin's collect/pre.yml on localhost and return its facts."""
    alias = plugin_name
    pre_tasks = PLUGINS_ROOT / plugin_name / "ansible" / "collect" / "pre.yml"
    playbook = tmp_path / "play.yml"
    playbook.write_text(
        f"""
- hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - ansible.builtin.include_tasks: {pre_tasks}
    - ansible.builtin.copy:
        dest: {tmp_path / "facts.json"}
        content: "{{{{ {{'is_remote': {alias}_k6_is_remote | bool,
          'key_path': {alias}_k6_ssh_key_path,
          'registered': '{alias}_k6' in hostvars}} | to_json }}}}"
"""
    )
    extravars = {
        "benchmark_config": {
            "plugin_settings": {
                plugin_name: {"k6_host": k6_host, "k6_ssh_key": "~/.ssh/k6_key"}
            }
        }
    }
    env = {**os.environ, "ANSIBLE_LOCAL_TEMP": str(tmp_path / "ansible-tmp")}
    proc = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            "localhost,",
            str(playbook),
            "-e",
            json.dumps(extravars),
        ],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads((tmp_path / "facts.json").read_text())


@pytest.mark.skipif(
    shutil.which("ansible-playbook") is None, reason="ansible-playbook not installed"
)
@pytest.mark.parametrize("plugin_name", ["dfaas", "peva_faas"])
@pytest.mark.parametrize(
    ("k6_host", "is_remote"),
    [("10.0.0.7", True), ("127.0.0.1", False), ("localhost", False)],
)
def test_faas_collect_pre_registers_k6_host_only_when_remote(
    tmp_path: Path, plugin_name: str, k6_host: str, is_remote: bool
) -> None:
    facts = _run_collect_pre(tmp_path, plugin_name, k6_host)
    assert facts["is_remote"] is is_remote
    assert facts["registered"] is is_remote
    assert facts["key_path"] == f"{Path.home()}/.ssh/k6_key"
