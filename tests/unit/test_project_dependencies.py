"""Sanity checks for project metadata."""

from __future__ import annotations

from pathlib import Path
import tomllib


def _load_pyproject() -> dict:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))


def _load_project_dependencies() -> list[str]:
    data = _load_pyproject()
    return list(data["project"]["dependencies"])


def _load_mypy_config() -> dict:
    data = _load_pyproject()
    return dict(data["tool"]["mypy"])


def test_invoke_is_declared_for_dfaas_extra() -> None:
    data = _load_pyproject()
    extras = data["project"]["optional-dependencies"]["dfaas"]
    assert any(dep.startswith("invoke") for dep in extras)


def test_mypy_excludes_molecule_dir() -> None:
    config = _load_mypy_config()
    exclude = config.get("exclude", "")
    assert "molecule" in exclude


def test_dfaas_deps_are_not_global() -> None:
    deps = _load_project_dependencies()
    assert not any(dep.startswith("fabric") for dep in deps)
    assert not any(dep.startswith("invoke") for dep in deps)


def test_dfaas_extra_contains_plugin_deps() -> None:
    data = _load_pyproject()
    extras = data["project"]["optional-dependencies"]["dfaas"]
    assert any(dep.startswith("fabric") for dep in extras)
    assert any(dep.startswith("invoke") for dep in extras)


def test_peva_faas_deps_are_not_global() -> None:
    deps = _load_project_dependencies()
    assert not any(dep.startswith("duckdb") for dep in deps)
    assert not any(dep.startswith("pyarrow") for dep in deps)


def test_peva_faas_extra_contains_plugin_deps() -> None:
    extras = _load_pyproject()["project"]["optional-dependencies"]["peva_faas"]
    assert any(dep.startswith("duckdb") for dep in extras)
    assert any(dep.startswith("pyarrow") for dep in extras)
