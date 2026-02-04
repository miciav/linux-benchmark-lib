"""Helpers for determining pending work in a run journal."""

from __future__ import annotations

from typing import Iterable, Sequence

from lb_controller.services.journal import RunJournal
from lb_runner.api import RemoteHostConfig


def pending_hosts_for(
    journal: RunJournal,
    target_reps: int,
    test_name: str,
    hosts: Sequence[RemoteHostConfig],
    *,
    allow_skipped: bool = False,
) -> list[RemoteHostConfig]:
    """Return hosts that still have repetitions to run for a workload."""
    pending: list[RemoteHostConfig] = []
    for host in hosts:
        for rep in range(1, target_reps + 1):
            if journal.should_run(
                host.name, test_name, rep, allow_skipped=allow_skipped
            ):
                pending.append(host)
                break
    return pending


def pending_repetitions(
    journal: RunJournal,
    target_reps: int,
    hosts: Sequence[RemoteHostConfig],
    test_name: str,
    *,
    allow_skipped: bool = False,
) -> dict[str, list[int]]:
    """Return the pending repetitions per host for a workload."""
    pending: dict[str, list[int]] = {}
    for host in hosts:
        reps_for_host = [
            rep
            for rep in range(1, target_reps + 1)
            if journal.should_run(
                host.name, test_name, rep, allow_skipped=allow_skipped
            )
        ]
        pending[host.name] = reps_for_host or [1]
    return pending


def pending_exists(
    journal: RunJournal,
    tests: Iterable[str],
    hosts: Sequence[RemoteHostConfig],
    repetitions: int,
    *,
    allow_skipped: bool = False,
) -> bool:
    """Return True if any repetition remains to run."""
    return any(
        journal.should_run(host.name, test_name, rep, allow_skipped=allow_skipped)
        for host in hosts
        for test_name in tests
        for rep in range(1, repetitions + 1)
    )
