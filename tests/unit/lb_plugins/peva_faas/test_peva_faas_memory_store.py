from __future__ import annotations

from pathlib import Path

import pytest

from lb_plugins.plugins.peva_faas.services.memory_store import DuckDBMemoryStore

pytestmark = [pytest.mark.unit_plugins]


def test_store_bootstrap_creates_schema_meta(tmp_path: Path) -> None:
    db_path = tmp_path / "mem.duckdb"
    store = DuckDBMemoryStore(db_path=db_path, schema_version="peva_faas_mem_v1")

    store.startup()
    try:
        assert db_path.exists()
        assert store.schema_version() == "peva_faas_mem_v1"
    finally:
        store.close()


def test_store_rejects_schema_mismatch(tmp_path: Path) -> None:
    db_path = tmp_path / "mem.duckdb"
    store = DuckDBMemoryStore(db_path=db_path, schema_version="peva_faas_mem_v1")
    store.startup()
    try:
        with pytest.raises(ValueError, match="schema_version"):
            store.validate_preload_schema("peva_faas_mem_v2")
    finally:
        store.close()
