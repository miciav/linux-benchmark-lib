import pytest
from pydantic import ValidationError

from lb_runner.api import BenchmarkConfig, validate_experiment_id

pytestmark = pytest.mark.unit_runner


@pytest.mark.parametrize("value", ["tuning-io", "exp-20261009-151200", "a", "A.b_c-1"])
def test_valid_experiment_ids_are_accepted(value: str) -> None:
    assert BenchmarkConfig(experiment_id=value).experiment_id == value
    assert validate_experiment_id(value) == value


@pytest.mark.parametrize(
    "value", ["", "has space", "a/b", "..", "-leading", "x" * 65, "ünïcode"]
)
def test_invalid_experiment_ids_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError, match="experiment"):
        BenchmarkConfig(experiment_id=value)
    with pytest.raises(ValueError, match="letters, digits"):
        validate_experiment_id(value)


def test_experiment_id_defaults_to_none() -> None:
    assert BenchmarkConfig().experiment_id is None
    assert validate_experiment_id(None) is None


def test_the_run_prefix_is_reserved_for_run_ids() -> None:
    # Older runs without an id are listed as experiments named by run_id.
    with pytest.raises(ValueError, match="reserved"):
        validate_experiment_id("run-20261001-090000")
    with pytest.raises(ValidationError, match="reserved"):
        BenchmarkConfig(experiment_id="run-x")
    assert validate_experiment_id("running-tests") == "running-tests"
