"""Shared command-style generator helpers for plugins."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..base_generator import CommandGenerator


class ProcessCommandGenerator(CommandGenerator):
    """Command generator with standard process output handling."""

    tool_name: str | None = None

    def _ensure_tool(self, tool_name: str) -> bool:
        if shutil.which(tool_name) is None:
            logger = logging.getLogger(self.__class__.__module__)
            logger.error("%s binary not found in PATH.", tool_name)
            return False
        return True

    def _validate_environment(self) -> bool:
        if self.tool_name:
            return self._ensure_tool(self.tool_name)
        return True

    def _consume_process_output(self, proc: subprocess.Popen[str]) -> tuple[str, str]:
        stdout, stderr = proc.communicate(timeout=self._timeout_seconds())
        return stdout or "", stderr or ""


class StdoutCommandGenerator(ProcessCommandGenerator):
    """Command generator with standard stdout/stderr handling."""

    tool_name: str = "command"

    def _command_workdir(self) -> Path | None:
        return None

    def _popen_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
        }
        workdir = self._command_workdir()
        if workdir is not None:
            kwargs["cwd"] = workdir
        return kwargs

    def _log_failure(
        self, returncode: int, stdout: str, stderr: str, cmd: list[str]
    ) -> None:
        output = stdout or stderr
        logger = logging.getLogger(self.__class__.__module__)
        label = self.tool_name or self.name
        if output:
            logger.error("%s failed with return code %s: %s", label, returncode, output)
        else:
            logger.error("%s failed with return code %s", label, returncode)
