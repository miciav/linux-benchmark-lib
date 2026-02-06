from pathlib import Path

from tests.e2e import test_dfaas_multipass_e2e as suite
from tests.e2e.test_multipass_benchmark import multipass_vm  # noqa: F401

pytestmark = suite.pytestmark
multipass_two_vms = suite.multipass_two_vms


def test_peva_faas_multipass_cli_workflow(multipass_two_vms, tmp_path: Path) -> None:
    suite.run_peva_faas_multipass_cli_workflow(multipass_two_vms, tmp_path)


def test_peva_faas_multipass_stopfile_duckdb_e2e(
    multipass_two_vms, tmp_path: Path
) -> None:
    suite.run_peva_faas_multipass_stopfile_duckdb_e2e(multipass_two_vms, tmp_path)
