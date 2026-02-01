"""Builder for controller run sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from lb_controller.engine.run_state import RunState
from lb_controller.engine.run_state_builders import (
    ExtravarsBuilder,
    RunDirectoryPreparer,
    build_inventory,
    resolve_run_id,
)
from lb_controller.engine.session import RunSession
from lb_controller.engine.stops import StopCoordinator
from lb_controller.models.state import ControllerStateMachine
from lb_controller.services.journal import RunJournal
from lb_runner.api import BenchmarkConfig


class RunSessionBuilder:
    """Prepare RunSession instances for controller runs."""

    def __init__(
        self,
        *,
        config: BenchmarkConfig,
        state_machine: ControllerStateMachine,
        stop_timeout_s: float,
        journal_refresh: Callable[[], None] | None,
        collector_packages: Callable[[], set[str]],
    ) -> None:
        self._config = config
        self._state_machine = state_machine
        self._stop_timeout_s = stop_timeout_s
        self._journal_refresh = journal_refresh
        self._collector_packages = collector_packages

    def build(
        self,
        test_types: list[str],
        run_id: Optional[str],
        journal: Optional[RunJournal],
        journal_path: Optional[Path],
    ) -> RunSession:
        resolved_run_id = resolve_run_id(run_id, journal)
        inventory = build_inventory(self._config)

        coordinator = StopCoordinator(
            expected_runners={h.name for h in self._config.remote_hosts},
            stop_timeout=self._stop_timeout_s,
            run_id=resolved_run_id,
        )

        target_reps = (
            journal.metadata.get("repetitions") if journal else None
        ) or self._config.repetitions

        output_root, report_root, data_export_root, per_host_output = (
            RunDirectoryPreparer(self._config).prepare(resolved_run_id)
        )

        active_journal = journal or RunJournal.initialize(
            resolved_run_id, self._config, test_types
        )
        journal_file = journal_path or output_root / "run_journal.json"
        active_journal.save(journal_file)
        if self._journal_refresh:
            self._journal_refresh()

        extravars = ExtravarsBuilder(self._config).build(
            run_id=resolved_run_id,
            output_root=output_root,
            report_root=report_root,
            data_export_root=data_export_root,
            per_host_output=per_host_output,
            target_reps=target_reps,
            collector_packages=self._collector_packages(),
        )

        state = RunState(
            resolved_run_id=resolved_run_id,
            inventory=inventory,
            target_reps=target_reps,
            output_root=output_root,
            report_root=report_root,
            data_export_root=data_export_root,
            per_host_output=per_host_output,
            active_journal=active_journal,
            journal_file=journal_file,
            extravars=extravars,
            test_types=list(test_types),
        )

        return RunSession(state, coordinator, self._state_machine)
