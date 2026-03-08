"""Shared configuration enumeration helpers for FaaS plugins."""

from __future__ import annotations

import hashlib
from itertools import combinations, product
from typing import Iterable, Iterator, Sequence


def generate_function_combinations(
    functions: Sequence[str],
    min_functions: int,
    max_functions: int,
) -> list[tuple[str, ...]]:
    """Return deterministic function combinations for the configured bounds."""
    sorted_functions = sorted(functions)
    combos: list[tuple[str, ...]] = []
    for size in range(min_functions, max_functions):
        combos.extend(combinations(sorted_functions, size))
    return combos


def iter_configurations(
    functions: Sequence[str],
    rates: Sequence[int],
    min_functions: int,
    max_functions: int,
    rates_by_function: dict[str, list[int]] | None = None,
) -> Iterator[list[tuple[str, int]]]:
    """Yield configurations lazily instead of materializing the full product."""
    combos = generate_function_combinations(functions, min_functions, max_functions)
    for combo in combos:
        yield from _iter_configurations_for_combo(
            combo,
            rates,
            rates_by_function=rates_by_function,
        )


def generate_configurations(
    functions: Sequence[str],
    rates: Sequence[int],
    min_functions: int,
    max_functions: int,
    rates_by_function: dict[str, list[int]] | None = None,
) -> list[list[tuple[str, int]]]:
    """Materialize all configurations for callers that need the full plan."""
    return list(
        iter_configurations(
            functions,
            rates,
            min_functions,
            max_functions,
            rates_by_function=rates_by_function,
        )
    )


def count_configurations(
    functions: Sequence[str],
    rates: Sequence[int],
    min_functions: int,
    max_functions: int,
    rates_by_function: dict[str, list[int]] | None = None,
) -> int:
    """Count configurations without materializing the full Cartesian product."""
    total = 0
    for combo in generate_function_combinations(functions, min_functions, max_functions):
        combo_total = 1
        for fn in combo:
            combo_total *= len(_rates_for_function(fn, rates, rates_by_function))
        total += combo_total
    return total


def _iter_configurations_for_combo(
    combo: tuple[str, ...],
    rates: Sequence[int],
    *,
    rates_by_function: dict[str, list[int]] | None,
) -> Iterator[list[tuple[str, int]]]:
    rate_sets = [
        [(fn, rate) for rate in _rates_for_function(fn, rates, rates_by_function)]
        for fn in combo
    ]
    for selection in product(*rate_sets):
        yield list(selection)


def _rates_for_function(
    fn: str,
    rates: Sequence[int],
    rates_by_function: dict[str, list[int]] | None,
) -> list[int]:
    if not rates_by_function:
        return list(rates)
    return rates_by_function.get(fn, list(rates))


def config_key(
    config: Iterable[tuple[str, int]],
) -> tuple[tuple[str, ...], tuple[int, ...]]:
    """Return a deterministic key for a config regardless of input order."""
    sorted_config = sorted(config, key=lambda pair: pair[0])
    names = tuple(fn for fn, _ in sorted_config)
    rates = tuple(rate for _, rate in sorted_config)
    return names, rates


def config_id(config: Iterable[tuple[str, int]]) -> str:
    """Return a stable short identifier for a config."""
    names, rates = config_key(config)
    payload = "|".join(f"{name}:{rate}" for name, rate in zip(names, rates))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def dominates(
    base_config: Iterable[tuple[str, int]] | None,
    candidate_config: Iterable[tuple[str, int]],
) -> bool:
    """Return whether the candidate dominates the base on equal functions."""
    if base_config is None:
        return False
    base_names, base_rates = config_key(base_config)
    candidate_names, candidate_rates = config_key(candidate_config)
    if base_names != candidate_names:
        return False
    better = False
    for base_rate, candidate_rate in zip(base_rates, candidate_rates):
        if candidate_rate < base_rate:
            return False
        if candidate_rate > base_rate:
            better = True
    return better
