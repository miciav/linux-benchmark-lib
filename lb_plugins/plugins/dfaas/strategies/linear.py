"""Linear rate generation strategy."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import RateStrategy


class LinearRateStrategy(RateStrategy):
    """Generate rates with linear increments.

    This is the default strategy, matching the original behavior.
    Produces a sequence: [min_rate, min_rate+step, min_rate+2*step, ..., max_rate]
    """

    type: Literal["linear"] = "linear"
    min_rate: int = Field(default=0, ge=0, description="Minimum requests per second")
    max_rate: int = Field(default=200, ge=0, description="Maximum requests per second")
    step: int = Field(default=10, gt=0, description="Step between rates")

    @model_validator(mode="after")
    def _validate_bounds(self) -> "LinearRateStrategy":
        if self.max_rate < self.min_rate:
            raise ValueError("max_rate must be >= min_rate")
        return self

    def generate_rates(self) -> list[int]:
        """Generate linearly spaced rates."""
        return list(range(self.min_rate, self.max_rate + 1, self.step))

    def description(self) -> str:
        """Return human-readable description."""
        return f"Linear: {self.min_rate} to {self.max_rate} step {self.step}"
