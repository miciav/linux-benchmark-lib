"""Planning helpers for DFaaS configurations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable

from ..config import DfaasConfig


_DURATION_RE = re.compile(r"^(?P<value>[0-9]+)(?P<unit>ms|s|m|h)$")


def parse_duration_seconds(duration: str) -> int:
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
    return list(range(min_rate, max_rate + 1, step))


def generate_function_combinations(
    functions: list[str], min_functions: int, max_functions: int
) -> list[tuple[str, ...]]:
    from itertools import combinations

    sorted_functions = sorted(functions)
    combos: list[tuple[str, ...]] = []
    for size in range(min_functions, max_functions):
        combos.extend(combinations(sorted_functions, size))
    return combos


def generate_configurations(
    functions: list[str],
    rates: list[int],
    min_functions: int,
    max_functions: int,
    rates_by_function: dict[str, list[int]] | None = None,
) -> list[list[tuple[str, int]]]:
    from itertools import product

    configs: list[list[tuple[str, int]]] = []
    combos = generate_function_combinations(functions, min_functions, max_functions)
    for combo in combos:
        rate_sets: list[list[tuple[str, int]]] = []
        for fn in combo:
            fn_rates = rates_by_function.get(fn, rates) if rates_by_function else rates
            rate_sets.append([(fn, rate) for rate in fn_rates])
        for selection in product(*rate_sets):
            configs.append(list(selection))
    return configs


def config_key(config: Iterable[tuple[str, int]]) -> tuple[tuple[str, ...], tuple[int, ...]]:
    sorted_config = sorted(config, key=lambda pair: pair[0])
    names = tuple(fn for fn, _ in sorted_config)
    rates = tuple(rate for _, rate in sorted_config)
    return names, rates


def config_id(config: Iterable[tuple[str, int]]) -> str:
    names, rates = config_key(config)
    payload = "|".join(f"{name}:{rate}" for name, rate in zip(names, rates))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def dominates(
    base_config: Iterable[tuple[str, int]] | None,
    candidate_config: Iterable[tuple[str, int]],
) -> bool:
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


@dataclass(frozen=True)
class DfaasPlanBuilder:
    """Builds DFaaS configuration plans from config inputs."""

    config: DfaasConfig

    def build_function_names(self) -> list[str]:
        return sorted(fn.name for fn in self.config.functions)

    def build_rates(self) -> list[int]:
        return generate_rates_list(
            self.config.rates.min_rate,
            self.config.rates.max_rate,
            self.config.rates.step,
        )

    def build_rates_by_function(self, rates: list[int]) -> dict[str, list[int]]:
        rates_by_function: dict[str, list[int]] = {}
        for fn in self.config.functions:
            if fn.max_rate is None:
                continue
            rates_by_function[fn.name] = [
                rate for rate in rates if rate <= fn.max_rate
            ]
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
        configs = self.build_configurations(
            self.build_function_names(),
            rates,
            rates_by_function,
        )
        return max(
            1,
            duration * max(1, self.config.iterations) * max(1, len(configs)),
        )
