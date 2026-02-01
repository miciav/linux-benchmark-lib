"""Rate generation strategies for DFaaS plugin.

This module provides different strategies for generating the list of rates
to test during a DFaaS benchmark run.

Available strategies:
- LinearRateStrategy: Linear increments (default, original behavior)
- RandomRateStrategy: Random sampling within a range
- ExponentialRateStrategy: Exponential growth (2^n, etc.)
- CustomRateStrategy: Explicit list of rates

Example YAML configuration:

    # Linear (default)
    rate_strategy:
      type: linear
      min_rate: 10
      max_rate: 100
      step: 10

    # Random sampling
    rate_strategy:
      type: random
      min_rate: 10
      max_rate: 200
      count: 15
      seed: 42

    # Exponential growth
    rate_strategy:
      type: exponential
      base: 2
      min_power: 2
      max_power: 7

    # Explicit list
    rate_strategy:
      type: custom
      rates: [1, 5, 10, 25, 50, 100]
"""

from .base import RateStrategy
from .custom import CustomRateStrategy
from .exponential import ExponentialRateStrategy
from .linear import LinearRateStrategy
from .random import RandomRateStrategy

__all__ = [
    "RateStrategy",
    "LinearRateStrategy",
    "RandomRateStrategy",
    "ExponentialRateStrategy",
    "CustomRateStrategy",
]
