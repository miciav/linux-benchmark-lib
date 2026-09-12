"""The provisioners must emit the exact CLI they are documented to emit.

These pin the argv because the lifecycle tests stub the whole provision() body,
so nothing else would notice a dropped flag.
"""

import pytest

from lb_provisioner.providers.docker import delete_container_argv, run_container_argv
from lb_provisioner.providers.multipass import delete_argv, info_argv, launch_argv

pytestmark = pytest.mark.unit_provisioner


def test_launch_argv_pins_resources_and_name():
    argv = launch_argv("lb-vm-1", "lts")

    assert argv[:2] == ["multipass", "launch"]
    assert argv[2] == "lts"
    assert argv[argv.index("--name") + 1] == "lb-vm-1"
    assert argv[argv.index("--cpus") + 1] == "4"
    assert argv[argv.index("--disk") + 1] == "20G"
    assert argv[argv.index("--memory") + 1] == "8G"


def test_info_argv_asks_for_json():
    assert info_argv("lb-vm-1") == [
        "multipass",
        "info",
        "lb-vm-1",
        "--format",
        "json",
    ]


def test_delete_argv_purges():
    assert "--purge" in delete_argv("lb-vm-1")
    assert delete_argv("lb-vm-1")[:3] == ["multipass", "delete", "lb-vm-1"]


def test_run_container_argv_publishes_port_and_runs_init():
    argv = run_container_argv("docker", "lb-1", 2201, "ubuntu:24.04", "echo hi")

    assert argv[0] == "docker"
    assert argv[1] == "run"
    assert argv[2] == "-d"
    # --rm keeps a crashed or forgotten run from leaking containers instead of
    # letting them pile up until the host fills its disk.
    assert "--rm" in argv
    assert argv[argv.index("--name") + 1] == "lb-1"
    # sshd inside the container keys off the hostname, so a dropped --hostname
    # breaks the ssh/hostname contract the provisioner relies on.
    assert argv.index("--hostname") == argv.index("--name") + 2
    assert argv[argv.index("--hostname") + 1] == "lb-1"
    assert argv[argv.index("-p") + 1] == "2201:22"
    assert argv[-3:] == ["bash", "-c", "echo hi"]
    # The image must sit after every flag and immediately before the command:
    # argv is [docker, run, -d, --rm, --name, n, --hostname, n, -p, p, IMAGE,
    # bash, -c, script], so the image is at len - 4.
    assert argv.index("ubuntu:24.04") == len(argv) - 4
    assert argv[argv.index("-p") + 2] == "ubuntu:24.04"


def test_delete_container_argv_removes_by_name():
    assert delete_container_argv("docker", "lb-1") == ["docker", "rm", "-f", "lb-1"]
