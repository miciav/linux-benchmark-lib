"""Unit tests for provisioning lifecycle and preservation logic."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lb_provisioner.providers.multipass as multipass_mod
from lb_provisioner.api import (
    ProvisionedNode,
    ProvisioningError,
    ProvisioningMode,
    ProvisioningRequest,
    ProvisioningResult,
)
from lb_provisioner.providers.multipass import MultipassProvisioner


@pytest.fixture
def nodes():
    mock_node1 = MagicMock(spec=ProvisionedNode)
    mock_node1.teardown = MagicMock()
    mock_node2 = MagicMock(spec=ProvisionedNode)
    mock_node2.teardown = MagicMock()
    return [mock_node1, mock_node2]


def test_destroy_all_teardowns_nodes_by_default(nodes):
    result = ProvisioningResult(nodes=nodes)
    result.destroy_all()

    for node in nodes:
        node.teardown.assert_called_once()


def test_destroy_all_skips_if_keep_nodes_is_true(nodes):
    result = ProvisioningResult(nodes=nodes, keep_nodes=True)
    result.destroy_all()

    for node in nodes:
        node.teardown.assert_not_called()


def test_destroy_all_skips_if_keep_nodes_set_dynamically(nodes):
    result = ProvisioningResult(nodes=nodes)
    result.keep_nodes = True
    result.destroy_all()

    for node in nodes:
        node.teardown.assert_not_called()


def test_multipass_provision_rolls_back_created_nodes_on_partial_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(multipass_mod.shutil, "which", lambda _name: "/usr/bin/multipass")
    monkeypatch.setattr(multipass_mod, "MAX_NODES", 3)

    request = ProvisioningRequest(
        mode=ProvisioningMode.MULTIPASS,
        count=3,
        node_names=["vm-a", "vm-b", "vm-c"],
        state_dir=tmp_path,
    )
    provisioner = MultipassProvisioner(base_state_dir=tmp_path)

    def fake_generate_keys(key_path: Path) -> None:
        key_path.write_text("private")
        key_path.with_suffix(".pub").write_text("public")

    launched: list[str] = []
    destroyed: list[str] = []

    def fake_launch(vm_name: str, _image: str) -> None:
        if vm_name == "vm-c":
            raise ProvisioningError("boom")
        launched.append(vm_name)

    def fake_get_ip(vm_name: str) -> str:
        return f"10.0.0.{len(launched)}"

    def fake_destroy(vm_name: str, key_path: Path, pub_path: Path) -> None:
        destroyed.append(vm_name)
        if key_path.exists():
            key_path.unlink()
        if pub_path.exists():
            pub_path.unlink()

    monkeypatch.setattr(provisioner, "_generate_ephemeral_keys", fake_generate_keys)
    monkeypatch.setattr(provisioner, "_launch_vm", fake_launch)
    monkeypatch.setattr(provisioner, "_get_ip_address", fake_get_ip)
    monkeypatch.setattr(provisioner, "_inject_ssh_key", lambda *_args: None)
    monkeypatch.setattr(provisioner, "_destroy_vm", fake_destroy)

    with pytest.raises(ProvisioningError, match="boom"):
        provisioner.provision(request)

    assert destroyed == ["vm-b", "vm-a"]
    assert not (tmp_path / "vm-a_id_rsa").exists()
    assert not (tmp_path / "vm-a_id_rsa.pub").exists()
    assert not (tmp_path / "vm-b_id_rsa").exists()
    assert not (tmp_path / "vm-b_id_rsa.pub").exists()
