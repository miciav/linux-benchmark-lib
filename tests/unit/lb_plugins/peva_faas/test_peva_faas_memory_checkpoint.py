from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from lb_plugins.plugins.peva_faas.services.memory_checkpoint import ParquetCheckpoint
from lb_plugins.plugins.peva_faas.services.memory_store import DuckDBMemoryStore

pytestmark = [pytest.mark.unit_plugins]


def _insert_fixture_data(db_path: Path) -> None:
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO execution_events(
                config_id, iteration, repetition, run_id, start_ts, end_ts,
                duration_s, skip_reason, payload_json
            )
            VALUES ('cfg-1', 1, 1, 'run-1', 1.0, 2.0, 1.0, NULL, '{}')
            """
        )
        conn.execute(
            """
            INSERT INTO k6_raw_summaries(
                config_id, iteration, repetition, run_id, summary_json, summary_size_bytes, ingested_at
            )
            VALUES ('cfg-1', 1, 1, 'run-1', '{}', 2, NOW())
            """
        )


def test_preload_imports_only_core_tables(tmp_path: Path) -> None:
    source_db = tmp_path / "source.duckdb"
    target_db = tmp_path / "target.duckdb"
    core_dir = tmp_path / "core"
    debug_dir = tmp_path / "debug"

    source_store = DuckDBMemoryStore(source_db, schema_version="peva_faas_mem_v1")
    source_store.startup()
    source_store.close()
    _insert_fixture_data(source_db)

    ParquetCheckpoint(source_db, "peva_faas_mem_v1").export_all(
        core_dir=core_dir, debug_dir=debug_dir
    )

    target_store = DuckDBMemoryStore(target_db, schema_version="peva_faas_mem_v1")
    target_store.startup()
    target_store.close()

    ParquetCheckpoint(target_db, "peva_faas_mem_v1").preload_core(core_dir)

    with duckdb.connect(str(target_db)) as conn:
        core_count = conn.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0]
        debug_count = conn.execute("SELECT COUNT(*) FROM k6_raw_summaries").fetchone()[0]
    assert core_count == 1
    assert debug_count == 0


def test_export_writes_core_and_debug_separately(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.duckdb"
    core_dir = tmp_path / "core"
    debug_dir = tmp_path / "debug"

    store = DuckDBMemoryStore(db_path, schema_version="peva_faas_mem_v1")
    store.startup()
    store.close()
    _insert_fixture_data(db_path)

    checkpoint = ParquetCheckpoint(db_path, "peva_faas_mem_v1")
    checkpoint.export_all(core_dir=core_dir, debug_dir=debug_dir)

    assert (core_dir / "execution_events.parquet").exists()
    assert (core_dir / "memory_schema_meta.parquet").exists()
    assert (debug_dir / "k6_raw_summaries.parquet").exists()
