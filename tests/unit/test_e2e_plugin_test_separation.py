from pathlib import Path
import re


def _test_defs(path: Path) -> list[str]:
    text = path.read_text()
    return re.findall(r"^def (test_[a-zA-Z0-9_]+)\(", text, flags=re.MULTILINE)


def test_dfaas_and_peva_e2e_tests_are_in_separate_files() -> None:
    dfaas_files = [
        Path("tests/e2e/test_dfaas_multipass_e2e.py"),
        Path("tests/e2e/test_dfaas_streaming_events_e2e.py"),
    ]
    peva_file = Path("tests/e2e/test_peva_faas_cli_workflow_e2e.py")

    for path in dfaas_files:
        defs = _test_defs(path)
        assert not any(name.startswith("test_peva_") for name in defs), (
            f"PEVA-faas tests must not live in {path}"
        )

    peva_defs = _test_defs(peva_file)
    assert not any(name.startswith("test_dfaas_") for name in peva_defs), (
        f"DFaaS tests must not live in {peva_file}"
    )
