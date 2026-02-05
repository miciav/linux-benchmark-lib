"""Random rate generation strategy."""

from __future__ import annotations

import random as random_module
from typing import Literal

from pydantic import Field, model_validator

from .base import RateStrategy


class RandomRateStrategy(RateStrategy):
    """Generate N random rates within a range.

    Useful for exploratory testing or reducing the configuration space
    while maintaining representative coverage.
    """

    type: Literal["random"] = "random"
    min_rate: int = Field(default=10, ge=0, description="Minimum rate (inclusive)")
    max_rate: int = Field(default=200, ge=0, description="Maximum rate (inclusive)")
    count: int = Field(default=10, ge=1, description="Number of rates to generate")
    seed: int | None = Field(
        default=None, description="Random seed for reproducibility"
    )

    @model_validator(mode="after")
    def _validate_bounds(self) -> "RandomRateStrategy":
        if self.max_rate < self.min_rate:
            raise ValueError("max_rate must be >= min_rate")
        return self

    def generate_rates(self) -> list[int]:
        """Generate random rates within the specified range."""
        rng = random_module.Random(self.seed)
        range_size = self.max_rate - self.min_rate + 1
        actual_count = min(self.count, range_size)

        if actual_count == range_size:
            # If requesting all possible values, just return the full range
            return list(range(self.min_rate, self.max_rate + 1))

        # Sample without replacement and sort
        population = range(self.min_rate, self.max_rate + 1)
        rates = sorted(rng.sample(list(population), actual_count))
        return rates

    def description(self) -> str:
        """Return human-readable description."""
        seed_info = f", seed={self.seed}" if self.seed is not None else ""
        return (
            f"Random: {self.count} rates in "
            f"[{self.min_rate}, {self.max_rate}]{seed_info}"
        )
