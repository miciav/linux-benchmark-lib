"""Policy algorithm loader for pluggable PEVA-faas strategies."""

from __future__ import annotations

from importlib import import_module

from .contracts import ConfigPairs, ExecutionEvent, PolicyAlgorithm


class NoOpPolicy:
    """Default policy preserving incoming candidate order."""

    def choose_batch(
        self, *, candidates: list[ConfigPairs], desired_size: int
    ) -> list[ConfigPairs]:
        return candidates[: max(0, desired_size)]

    def update_online(self, event: ExecutionEvent) -> None:
        _ = event

    def update_batch(self, events: list[ExecutionEvent]) -> None:
        _ = events


def load_policy_algorithm(entrypoint: str | None) -> PolicyAlgorithm:
    """Load policy algorithm from ``module:Class`` entrypoint."""
    if not entrypoint:
        return NoOpPolicy()
    try:
        module_name, class_name = entrypoint.split(":", 1)
    except ValueError as exc:
        raise ValueError(
            "algorithm_entrypoint must use 'module:Class' format"
        ) from exc
    module = import_module(module_name)
    algorithm_cls = getattr(module, class_name, None)
    if algorithm_cls is None:
        raise ValueError(f"Policy class '{class_name}' not found in '{module_name}'")
    instance = algorithm_cls()
    if not isinstance(instance, PolicyAlgorithm):
        raise TypeError(
            f"Loaded policy '{entrypoint}' does not implement PolicyAlgorithm contract"
        )
    return instance
