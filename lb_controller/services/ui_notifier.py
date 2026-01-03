"""UI notification helpers for controller phases and logs."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class UINotifier:
    """Encapsulate UI formatting and journal refresh callbacks."""

    def __init__(
        self,
        output_formatter: Any | None = None,
        journal_refresh: Callable[[], None] | None = None,
    ) -> None:
        self._output_formatter = output_formatter
        self._journal_refresh = journal_refresh

    def set_phase(self, phase: str) -> None:
        if self._output_formatter:
            self._output_formatter.set_phase(phase)

    def refresh_journal(self) -> None:
        if not self._journal_refresh:
            return
        try:
            self._journal_refresh()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Journal refresh callback failed: %s", exc)

    def log(self, message: str) -> None:
        logger.info(message)
