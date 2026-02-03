from __future__ import annotations

import os
from pathlib import Path

from lb_app.api import RunJournal
from lb_ui.presenters.journal import build_journal_table
from lb_ui.wiring.dependencies import UIContext


def resolve_stop_file(stop_file: Path | None) -> Path | None:
    if stop_file is not None:
        return stop_file
    env_value = os.environ.get("LB_STOP_FILE")
    return Path(env_value) if env_value else None


def print_run_journal_summary(
    ctx: UIContext,
    journal_path: Path,
    log_path: Path | None = None,
    ui_log_path: Path | None = None,
) -> None:
    try:
        journal = RunJournal.load(journal_path)
    except Exception as exc:
        ctx.ui.present.warning(f"Could not read run journal at {journal_path}: {exc}")
        if log_path:
            ctx.ui.present.info(f"Ansible output log: {log_path}")
        return

    ctx.ui.tables.show(build_journal_table(journal))

    ctx.ui.present.info(f"Journal saved to {journal_path}")
    if log_path:
        ctx.ui.present.info(f"Ansible output log saved to {log_path}")
    if ui_log_path:
        ctx.ui.present.info(f"Dashboard log stream saved to {ui_log_path}")
