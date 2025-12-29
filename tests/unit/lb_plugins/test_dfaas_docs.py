from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit_plugins]


def test_dfaas_readme_has_required_sections() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    readme = (repo_root / "lb_plugins" / "plugins" / "dfaas" / "README.md").read_text()
    for section in [
        "## Architecture",
        "## Prerequisites",
        "## Setup steps",
        "## Run flow",
        "## Outputs",
        "## Troubleshooting",
    ]:
        assert section in readme
