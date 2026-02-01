"""Base class for rate generation strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class RateStrategy(BaseModel, ABC):
    """Abstract base class for rate generation strategies.

    Each concrete strategy must:
    1. Define a `type` field with a Literal default value
    2. Implement `generate_rates()` to produce the list of rates
    3. Implement `description()` for human-readable representation
    """

    model_config = {"extra": "ignore"}

    @abstractmethod
    def generate_rates(self) -> list[int]:
        """Generate the list of rates to test.

        Returns:
            Sorted list of non-negative integer rates (requests per second).
        """
        ...

    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description of this strategy."""
        ...
