from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_bump_version_module(repo_root: Path):
    module_path = repo_root / "scripts" / "bump_version" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("Failed to load bump_version module spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_git_commands_updates_uv_lock(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "pyproject.toml").write_text('version = "1.2.3"\n')
    (repo_root / "uv.lock").write_text("")

    class DummyStyle:
        def __init__(self, *args, **kwargs):
            pass

    fake_questionary = types.SimpleNamespace(Style=DummyStyle)
    monkeypatch.setitem(sys.modules, "questionary", fake_questionary)

    bump_version = _load_bump_version_module(_project_root())

    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, check=False, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(bump_version.subprocess, "run", fake_run)

    assert bump_version.run_git_commands(
        repo_root, "1.2.4", "notes", dry_run=False
    )

    assert ["uv", "lock"] in calls
    uv_index = calls.index(["uv", "lock"])
    add_index = next(
        i for i, cmd in enumerate(calls) if cmd[:2] == ["git", "add"]
    )
    assert uv_index < add_index
    assert any(
        cmd[:2] == ["git", "add"] and "uv.lock" in cmd for cmd in calls
    )
