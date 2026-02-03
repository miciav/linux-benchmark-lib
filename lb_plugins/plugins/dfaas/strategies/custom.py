"""Custom rate list strategy."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from .base import RateStrategy


class CustomRateStrategy(RateStrategy):
    """Use an explicit list of rates.

    Provides full control over which exact rates to test.
    Rates are automatically sorted and deduplicated.
    """

    type: Literal["custom"] = "custom"
    rates: list[int] = Field(min_length=1, description="Explicit list of rates to test")

    @field_validator("rates")
    @classmethod
    def _validate_rates(cls, v: list[int]) -> list[int]:
        if any(r < 0 for r in v):
            raise ValueError("All rates must be >= 0")
        # Sort and deduplicate
        return sorted(set(v))

    def generate_rates(self) -> list[int]:
        """Return the configured rates."""
        return self.rates

    def description(self) -> str:
        """Return human-readable description."""
        if len(self.rates) <= 5:
            return f"Custom: {self.rates}"
        return f"Custom: {len(self.rates)} rates [{self.rates[0]}..{self.rates[-1]}]"
