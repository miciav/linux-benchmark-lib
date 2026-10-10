import pytest

from lb_app.services.run_context_builder import RunContextBuilder
from lb_runner.api import BenchmarkConfig

pytestmark = pytest.mark.unit_ui


def test_command_line_beats_the_config_file() -> None:
    cfg = BenchmarkConfig(experiment_id="from-config")
    RunContextBuilder._apply_experiment(cfg, "from-cli")
    assert cfg.experiment_id == "from-cli"


def test_no_command_line_keeps_the_config_value() -> None:
    cfg = BenchmarkConfig(experiment_id="from-config")
    RunContextBuilder._apply_experiment(cfg, None)
    assert cfg.experiment_id == "from-config"


@pytest.mark.parametrize("bad", ["", "a b", "../x"])
def test_an_invalid_command_line_id_fails_before_the_run(bad: str) -> None:
    with pytest.raises(ValueError, match="letters, digits"):
        RunContextBuilder._apply_experiment(BenchmarkConfig(), bad)
