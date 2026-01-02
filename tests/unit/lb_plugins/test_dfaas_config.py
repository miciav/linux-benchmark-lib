from pathlib import Path

import pytest
from pydantic import ValidationError

from lb_plugins.plugins.dfaas.config import DfaasConfig

pytestmark = [pytest.mark.unit_plugins]


def test_config_path_load_with_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "dfaas_config.yml"
    config_path.write_text(
        "\n".join(
            [
                "common:",
                "  timeout_buffer: 5",
                "plugins:",
                "  dfaas:",
                "    k6_host: \"10.0.0.50\"",
                "    functions:",
                "      - name: \"figlet\"",
                "        method: \"POST\"",
                "        body: \"Hello DFaaS!\"",
                "        headers:",
                "          Content-Type: \"text/plain\"",
                "    rates:",
                "      min_rate: 0",
                "      max_rate: 20",
                "      step: 10",
                "    combinations:",
                "      min_functions: 1",
                "      max_functions: 2",
            ]
        )
    )

    config = DfaasConfig(config_path=config_path, rates={"max_rate": 50})

    assert config.timeout_buffer == 5
    assert config.k6_host == "10.0.0.50"
    assert config.rates.min_rate == 0
    assert config.rates.max_rate == 50


def test_invalid_rate_bounds_rejected() -> None:
    with pytest.raises(ValidationError):
        DfaasConfig(rates={"min_rate": 20, "max_rate": 10, "step": 10})


def test_invalid_duration_rejected() -> None:
    with pytest.raises(ValidationError):
        DfaasConfig(duration="30")
