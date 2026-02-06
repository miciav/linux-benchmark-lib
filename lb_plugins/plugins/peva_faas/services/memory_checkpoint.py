"""Parquet import/export checkpoints for PEVA-faas memory data."""

from __future__ import annotations

from pathlib import Path

import duckdb


class ParquetCheckpoint:
    """Manage checkpoint export/import for core and debug memory tables."""

    CORE_TABLES = (
        "memory_schema_meta",
        "run_sessions",
        "config_catalog",
        "execution_events",
        "policy_updates",
    )
    DEBUG_TABLES = ("k6_raw_summaries",)

    def __init__(self, db_path: Path, schema_version: str) -> None:
        self._db_path = db_path
        self._schema_version = schema_version

    def export_core(self, output_dir: Path) -> None:
        """Export core tables to Parquet files."""
        self._export_tables(self.CORE_TABLES, output_dir)

    def export_debug(self, output_dir: Path) -> None:
        """Export debug-only tables to Parquet files."""
        self._export_tables(self.DEBUG_TABLES, output_dir)

    def export_all(self, *, core_dir: Path, debug_dir: Path) -> None:
        """Export both core and debug checkpoints."""
        self.export_core(core_dir)
        self.export_debug(debug_dir)

    def preload_core(self, input_dir: Path) -> None:
        """Import only core tables after validating schema version."""
        meta_file = input_dir / "memory_schema_meta.parquet"
        if not meta_file.exists():
            raise ValueError("Missing memory_schema_meta.parquet in preload directory")
        self._validate_schema(meta_file)
        self._import_tables(self.CORE_TABLES, input_dir)

    def _export_tables(self, tables: tuple[str, ...], output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self._db_path)) as conn:
            for table in tables:
                out_file = output_dir / f"{table}.parquet"
                conn.execute(
                    f"COPY (SELECT * FROM {table}) TO ? (FORMAT PARQUET)",
                    [str(out_file)],
                )

    def _import_tables(self, tables: tuple[str, ...], input_dir: Path) -> None:
        with duckdb.connect(str(self._db_path)) as conn:
            for table in tables:
                in_file = input_dir / f"{table}.parquet"
                if not in_file.exists():
                    continue
                conn.execute(f"DELETE FROM {table}")
                conn.execute(
                    f"INSERT INTO {table} BY NAME SELECT * FROM read_parquet(?)",
                    [str(in_file)],
                )

    def _validate_schema(self, meta_file: Path) -> None:
        with duckdb.connect(str(self._db_path)) as conn:
            row = conn.execute(
                "SELECT schema_version FROM read_parquet(?) LIMIT 1",
                [str(meta_file)],
            ).fetchone()
        if row is None:
            raise ValueError("Invalid memory_schema_meta.parquet: missing schema_version")
        loaded_schema = str(row[0])
        if loaded_schema != self._schema_version:
            raise ValueError(
                "schema_version mismatch: "
                f"expected={self._schema_version} actual={loaded_schema}"
            )
