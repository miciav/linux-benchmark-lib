from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from lb_app.services.config_service import ConfigService


def test_open_editor_splits_editor_command_with_flags(tmp_path: Path) -> None:
    service = ConfigService()
    config_path = tmp_path / "benchmark_config.json"
    config_path.write_text("{}")

    with patch.object(
        service,
        "resolve_config_path",
        return_value=(config_path, None),
    ):
        with patch.dict(os.environ, {"EDITOR": "code -w"}):
            with patch.object(subprocess, "run") as run_mock:
                resolved = service.open_editor(None)

    run_mock.assert_called_once_with(["code", "-w", str(config_path)], check=False)
    assert resolved == config_path
