"""Tests for DFaaS rate generation strategies."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from lb_plugins.plugins.dfaas.config import DfaasConfig
from lb_plugins.plugins.dfaas.strategies import (
    CustomRateStrategy,
    ExponentialRateStrategy,
    LinearRateStrategy,
    RandomRateStrategy,
)

pytestmark = [pytest.mark.unit_plugins]


# --- LinearRateStrategy tests ---


class TestLinearRateStrategy:
    def test_default_values(self) -> None:
        strategy = LinearRateStrategy()
        assert strategy.type == "linear"
        assert strategy.min_rate == 0
        assert strategy.max_rate == 200
        assert strategy.step == 10

    def test_generate_rates_default(self) -> None:
        strategy = LinearRateStrategy()
        rates = strategy.generate_rates()
        assert rates == list(range(0, 201, 10))
        assert len(rates) == 21

    def test_generate_rates_custom(self) -> None:
        strategy = LinearRateStrategy(min_rate=10, max_rate=50, step=10)
        rates = strategy.generate_rates()
        assert rates == [10, 20, 30, 40, 50]

    def test_generate_rates_single_value(self) -> None:
        strategy = LinearRateStrategy(min_rate=100, max_rate=100, step=10)
        rates = strategy.generate_rates()
        assert rates == [100]

    def test_invalid_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LinearRateStrategy(min_rate=100, max_rate=50, step=10)

    def test_description(self) -> None:
        strategy = LinearRateStrategy(min_rate=10, max_rate=100, step=5)
        assert strategy.description() == "Linear: 10 to 100 step 5"


# --- RandomRateStrategy tests ---


class TestRandomRateStrategy:
    def test_default_values(self) -> None:
        strategy = RandomRateStrategy()
        assert strategy.type == "random"
        assert strategy.min_rate == 10
        assert strategy.max_rate == 200
        assert strategy.count == 10
        assert strategy.seed is None

    def test_generate_rates_count(self) -> None:
        strategy = RandomRateStrategy(min_rate=1, max_rate=100, count=5, seed=42)
        rates = strategy.generate_rates()
        assert len(rates) == 5
        assert all(1 <= r <= 100 for r in rates)

    def test_generate_rates_sorted(self) -> None:
        strategy = RandomRateStrategy(min_rate=1, max_rate=100, count=10, seed=42)
        rates = strategy.generate_rates()
        assert rates == sorted(rates)

    def test_generate_rates_reproducible_with_seed(self) -> None:
        strategy1 = RandomRateStrategy(min_rate=1, max_rate=100, count=10, seed=42)
        strategy2 = RandomRateStrategy(min_rate=1, max_rate=100, count=10, seed=42)
        assert strategy1.generate_rates() == strategy2.generate_rates()

    def test_generate_rates_different_without_seed(self) -> None:
        strategy1 = RandomRateStrategy(min_rate=1, max_rate=1000, count=10, seed=1)
        strategy2 = RandomRateStrategy(min_rate=1, max_rate=1000, count=10, seed=2)
        # Different seeds should produce different results (with high probability)
        assert strategy1.generate_rates() != strategy2.generate_rates()

    def test_generate_rates_count_exceeds_range(self) -> None:
        # Requesting more rates than available in range
        strategy = RandomRateStrategy(min_rate=1, max_rate=5, count=100, seed=42)
        rates = strategy.generate_rates()
        # Should return all possible values
        assert rates == [1, 2, 3, 4, 5]

    def test_invalid_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RandomRateStrategy(min_rate=100, max_rate=50)

    def test_description_with_seed(self) -> None:
        strategy = RandomRateStrategy(min_rate=10, max_rate=100, count=5, seed=42)
        assert "Random: 5 rates in [10, 100]" in strategy.description()
        assert "seed=42" in strategy.description()

    def test_description_without_seed(self) -> None:
        strategy = RandomRateStrategy(min_rate=10, max_rate=100, count=5)
        assert strategy.description() == "Random: 5 rates in [10, 100]"


# --- ExponentialRateStrategy tests ---


class TestExponentialRateStrategy:
    def test_default_values(self) -> None:
        strategy = ExponentialRateStrategy()
        assert strategy.type == "exponential"
        assert strategy.base == 2
        assert strategy.min_power == 0
        assert strategy.max_power == 8
        assert strategy.max_rate is None

    def test_generate_rates_default(self) -> None:
        strategy = ExponentialRateStrategy()
        rates = strategy.generate_rates()
        # 2^0, 2^1, 2^2, ..., 2^8
        assert rates == [1, 2, 4, 8, 16, 32, 64, 128, 256]

    def test_generate_rates_base_10(self) -> None:
        strategy = ExponentialRateStrategy(base=10, min_power=0, max_power=3)
        rates = strategy.generate_rates()
        assert rates == [1, 10, 100, 1000]

    def test_generate_rates_with_max_rate_cap(self) -> None:
        strategy = ExponentialRateStrategy(
            base=2, min_power=0, max_power=10, max_rate=100
        )
        rates = strategy.generate_rates()
        # 2^0=1, 2^1=2, ..., 2^6=64 (2^7=128 > 100, stop)
        assert rates == [1, 2, 4, 8, 16, 32, 64]

    def test_generate_rates_custom_power_range(self) -> None:
        strategy = ExponentialRateStrategy(base=2, min_power=3, max_power=6)
        rates = strategy.generate_rates()
        # 2^3=8, 2^4=16, 2^5=32, 2^6=64
        assert rates == [8, 16, 32, 64]

    def test_invalid_power_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExponentialRateStrategy(min_power=5, max_power=3)

    def test_description_without_cap(self) -> None:
        strategy = ExponentialRateStrategy(base=2, min_power=0, max_power=5)
        assert strategy.description() == "Exponential: 2^[0..5]"

    def test_description_with_cap(self) -> None:
        strategy = ExponentialRateStrategy(
            base=2, min_power=0, max_power=10, max_rate=100
        )
        assert strategy.description() == "Exponential: 2^[0..10], capped at 100"


# --- CustomRateStrategy tests ---


class TestCustomRateStrategy:
    def test_generate_rates(self) -> None:
        strategy = CustomRateStrategy(rates=[50, 10, 100, 25])
        rates = strategy.generate_rates()
        # Should be sorted and deduplicated
        assert rates == [10, 25, 50, 100]

    def test_rates_deduplicated(self) -> None:
        strategy = CustomRateStrategy(rates=[10, 20, 10, 30, 20])
        rates = strategy.generate_rates()
        assert rates == [10, 20, 30]

    def test_empty_rates_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CustomRateStrategy(rates=[])

    def test_negative_rates_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CustomRateStrategy(rates=[10, -5, 20])

    def test_description_short_list(self) -> None:
        strategy = CustomRateStrategy(rates=[1, 5, 10])
        assert strategy.description() == "Custom: [1, 5, 10]"

    def test_description_long_list(self) -> None:
        strategy = CustomRateStrategy(rates=[1, 5, 10, 20, 50, 100])
        assert strategy.description() == "Custom: 6 rates [1..100]"


# --- DfaasConfig integration tests ---


class TestDfaasConfigRateStrategy:
    def test_default_strategy_is_linear(self) -> None:
        config = DfaasConfig()
        assert isinstance(config.rate_strategy, LinearRateStrategy)

    def test_linear_strategy_from_dict(self) -> None:
        config = DfaasConfig(
            rate_strategy={"type": "linear", "min_rate": 10, "max_rate": 50, "step": 10}
        )
        assert isinstance(config.rate_strategy, LinearRateStrategy)
        assert config.rate_strategy.generate_rates() == [10, 20, 30, 40, 50]

    def test_random_strategy_from_dict(self) -> None:
        config = DfaasConfig(
            rate_strategy={
                "type": "random",
                "min_rate": 10,
                "max_rate": 100,
                "count": 5,
                "seed": 42,
            }
        )
        assert isinstance(config.rate_strategy, RandomRateStrategy)
        assert len(config.rate_strategy.generate_rates()) == 5

    def test_exponential_strategy_from_dict(self) -> None:
        config = DfaasConfig(
            rate_strategy={
                "type": "exponential",
                "base": 2,
                "min_power": 2,
                "max_power": 5,
            }
        )
        assert isinstance(config.rate_strategy, ExponentialRateStrategy)
        assert config.rate_strategy.generate_rates() == [4, 8, 16, 32]

    def test_custom_strategy_from_dict(self) -> None:
        config = DfaasConfig(rate_strategy={"type": "custom", "rates": [10, 50, 100]})
        assert isinstance(config.rate_strategy, CustomRateStrategy)
        assert config.rate_strategy.generate_rates() == [10, 50, 100]

    def test_invalid_strategy_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DfaasConfig(rate_strategy={"type": "invalid_type"})

    def test_legacy_rates_migrated_to_strategy(self) -> None:
        with pytest.warns(DeprecationWarning):
            config = DfaasConfig(rates={"min_rate": 10, "max_rate": 50, "step": 5})

        # Legacy rates should be migrated to rate_strategy
        assert isinstance(config.rate_strategy, LinearRateStrategy)
        assert config.rate_strategy.min_rate == 10
        assert config.rate_strategy.max_rate == 50
        assert config.rate_strategy.step == 5

    def test_rate_strategy_from_yaml(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "\n".join(
                [
                    "plugins:",
                    "  dfaas:",
                    "    rate_strategy:",
                    "      type: random",
                    "      min_rate: 10",
                    "      max_rate: 100",
                    "      count: 8",
                    "      seed: 123",
                    "    functions:",
                    "      - name: test_func",
                ]
            )
        )

        config = DfaasConfig(config_path=config_path)
        assert isinstance(config.rate_strategy, RandomRateStrategy)
        assert config.rate_strategy.count == 8
        assert config.rate_strategy.seed == 123

    def test_function_max_rate_validated_against_strategy(self) -> None:
        # Function max_rate must be >= strategy min_rate
        with pytest.raises(ValidationError):
            DfaasConfig(
                rate_strategy={"type": "linear", "min_rate": 50, "max_rate": 100},
                functions=[{"name": "test", "max_rate": 30}],
            )
