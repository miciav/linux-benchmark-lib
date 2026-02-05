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
