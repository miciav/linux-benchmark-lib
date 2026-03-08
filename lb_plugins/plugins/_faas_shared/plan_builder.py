"""Shared plan builder primitives for FaaS-style plugins."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol, Sequence

from .config_enumerator import (
    config_id,
    config_key,
    count_configurations,
    dominates,
    generate_configurations,
    generate_function_combinations,
)


_DURATION_RE = re.compile(r"^(?P<value>[0-9]+)(?P<unit>ms|s|m|h)$")


def parse_duration_seconds(duration: str) -> int:
    """Parse a duration string into whole seconds."""
    match = _DURATION_RE.match(duration.strip())
    if not match:
        raise ValueError(f"Invalid duration format: {duration!r}")
    value = int(match.group("value"))
    unit = match.group("unit")
    if unit == "ms":
        return max(1, int(value / 1000))
    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    raise ValueError(f"Unsupported duration unit: {unit}")


def generate_rates_list(min_rate: int, max_rate: int, step: int) -> list[int]:
    """Generate an inclusive linear rate list."""
    return list(range(min_rate, max_rate + 1, step))


class _RateStrategyLike(Protocol):
    def generate_rates(self) -> list[int]:
        """Return the concrete rate list."""


class _FunctionConfigLike(Protocol):
    @property
    def name(self) -> str:
        """Function name."""

    @property
    def max_rate(self) -> int | None:
        """Optional per-function rate cap."""


class _CombinationConfigLike(Protocol):
    @property
    def min_functions(self) -> int:
        """Minimum number of functions per combination."""

    @property
    def max_functions(self) -> int:
        """Maximum number of functions per combination."""


class _PlanConfigLike(Protocol):
    @property
    def functions(self) -> Sequence[_FunctionConfigLike]:
        """Configured functions."""

    @property
    def rate_strategy(self) -> _RateStrategyLike:
        """Rate strategy."""

    @property
    def combinations(self) -> _CombinationConfigLike:
        """Combination settings."""

    @property
    def duration(self) -> str:
        """Workload duration string."""

    @property
    def iterations(self) -> int:
        """Iteration count."""


@dataclass(frozen=True)
class FaasPlanBuilder:
    """Build deterministic FaaS plans from shared config semantics."""

    config: _PlanConfigLike

    def build_function_names(self) -> list[str]:
        return sorted(fn.name for fn in self.config.functions)

    def build_rates(self) -> list[int]:
        """Generate rates using the configured strategy."""
        return self.config.rate_strategy.generate_rates()

    def build_rates_by_function(self, rates: list[int]) -> dict[str, list[int]]:
        rates_by_function: dict[str, list[int]] = {}
        for fn in self.config.functions:
            if fn.max_rate is None:
                continue
            rates_by_function[fn.name] = [rate for rate in rates if rate <= fn.max_rate]
        return rates_by_function

    def build_configurations(
        self,
        function_names: list[str],
        rates: list[int],
        rates_by_function: dict[str, list[int]] | None = None,
    ) -> list[list[tuple[str, int]]]:
        return generate_configurations(
            function_names,
            rates,
            self.config.combinations.min_functions,
            self.config.combinations.max_functions,
            rates_by_function=rates_by_function,
        )

    def estimate_runtime_seconds(self) -> int:
        duration = parse_duration_seconds(self.config.duration)
        rates = self.build_rates()
        rates_by_function = self.build_rates_by_function(rates)
        config_count = count_configurations(
            self.build_function_names(),
            rates,
            self.config.combinations.min_functions,
            self.config.combinations.max_functions,
            rates_by_function=rates_by_function,
        )
        return max(
            1,
            duration * max(1, self.config.iterations) * max(1, config_count),
        )


__all__ = [
    "FaasPlanBuilder",
    "config_id",
    "config_key",
    "count_configurations",
    "dominates",
    "generate_configurations",
    "generate_function_combinations",
    "generate_rates_list",
    "parse_duration_seconds",
]
