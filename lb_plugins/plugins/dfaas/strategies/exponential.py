"""Exponential rate generation strategy."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import RateStrategy


class ExponentialRateStrategy(RateStrategy):
    """Generate rates with exponential growth (base^power).

    Useful for stress testing where you want to quickly escalate load
    to find breaking points.
    """

    type: Literal["exponential"] = "exponential"
    base: int = Field(default=2, ge=2, description="Exponential base")
    min_power: int = Field(default=0, ge=0, description="Starting power (inclusive)")
    max_power: int = Field(default=8, ge=0, description="Ending power (inclusive)")
    max_rate: int | None = Field(
        default=None, ge=1, description="Optional cap on maximum rate"
    )

    @model_validator(mode="after")
    def _validate_bounds(self) -> "ExponentialRateStrategy":
        if self.max_power < self.min_power:
            raise ValueError("max_power must be >= min_power")
        return self

    def generate_rates(self) -> list[int]:
        """Generate exponentially growing rates."""
        rates: list[int] = []
        for power in range(self.min_power, self.max_power + 1):
            rate = self.base**power
            if self.max_rate is not None and rate > self.max_rate:
                break
            rates.append(rate)
        return rates

    def description(self) -> str:
        """Return human-readable description."""
        cap_info = f", capped at {self.max_rate}" if self.max_rate else ""
        return (
            f"Exponential: {self.base}^[{self.min_power}..{self.max_power}]"
            f"{cap_info}"
        )
