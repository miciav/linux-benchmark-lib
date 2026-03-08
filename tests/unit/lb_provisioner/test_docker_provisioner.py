from __future__ import annotations

from pathlib import Path

import pytest

import lb_provisioner.providers.docker as docker_mod
from lb_provisioner.api import ProvisioningError, ProvisioningMode, ProvisioningRequest
from lb_provisioner.providers.docker import DockerProvisioner


def test_docker_provision_rolls_back_created_nodes_on_partial_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_mod.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(docker_mod, "MAX_NODES", 3)

    request = ProvisioningRequest(
        mode=ProvisioningMode.DOCKER,
        count=3,
        docker_engine="docker",
        node_names=["ct-a", "ct-b", "ct-c"],
        state_dir=tmp_path,
    )
    provisioner = DockerProvisioner()

    def fake_generate_keys(key_path: Path) -> None:
        key_path.write_text("private")
        key_path.with_name(f"{key_path.name}.pub").write_text("public")

    destroyed: list[str] = []

    def fake_run_container(_engine: str, _image: str, name: str, _port: int) -> None:
        if name == "ct-c":
            raise ProvisioningError("boom")

    def fake_destroy(
        _engine: str,
        name: str,
        key_path: Path,
        pub_path: Path,
    ) -> None:
        destroyed.append(name)
        if key_path.exists():
            key_path.unlink()
        if pub_path.exists():
            pub_path.unlink()

    monkeypatch.setattr(provisioner, "_generate_ssh_keypair", fake_generate_keys)
    monkeypatch.setattr(provisioner, "_find_free_port", lambda: 2222)
    monkeypatch.setattr(provisioner, "_run_container", fake_run_container)
    monkeypatch.setattr(provisioner, "_inject_ssh_key", lambda *_args: None)
    monkeypatch.setattr(provisioner, "_wait_for_ssh", lambda *_args: None)
    monkeypatch.setattr(provisioner, "_destroy_container", fake_destroy)

    with pytest.raises(ProvisioningError, match="boom"):
        provisioner.provision(request)

    assert destroyed == ["ct-b", "ct-a"]
    assert not (tmp_path / "ct-a_id_rsa").exists()
    assert not (tmp_path / "ct-a_id_rsa.pub").exists()
    assert not (tmp_path / "ct-b_id_rsa").exists()
    assert not (tmp_path / "ct-b_id_rsa.pub").exists()
