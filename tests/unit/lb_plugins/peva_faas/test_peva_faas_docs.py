from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit_plugins]


def test_peva_faas_readme_has_required_sections() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    readme = (
        repo_root / "lb_plugins" / "plugins" / "peva_faas" / "README.md"
    ).read_text()
    # Check for required documentation sections
    for section in [
        "## Architecture",
        "## Prerequisites",
        "## Setup steps",
        "## Run flow",
        "## Outputs",
        "## Troubleshooting",
    ]:
        assert section in readme, f"Missing section: {section}"


def test_readme_documents_memory_core_and_debug_archive_split() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    readme = (
        repo_root / "lb_plugins" / "plugins" / "peva_faas" / "README.md"
    ).read_text()

    assert "Memory Core" in readme
    assert "Debug Archive" in readme


def test_readme_documents_online_and_micro_batch_modes() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    readme = (
        repo_root / "lb_plugins" / "plugins" / "peva_faas" / "README.md"
    ).read_text()

    assert "online" in readme
    assert "micro_batch" in readme


def test_readme_mentions_plugin_scoped_extra_and_setup_lifecycle() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    readme = (
        repo_root / "lb_plugins" / "plugins" / "peva_faas" / "README.md"
    ).read_text()

    assert "optional dependency extra `peva_faas`" in readme
    assert "setup_plugin.yml" in readme


def test_plugin_dependency_lifecycle_doc_exists() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    doc = repo_root / "docs" / "architecture" / "plugin-dependency-lifecycle.md"
    text = doc.read_text()

    assert "Plugin-scoped UV extras" in text
    assert "lb_uv_extras" in text
