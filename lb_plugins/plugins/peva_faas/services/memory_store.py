"""DuckDB-backed persistent memory store for PEVA-faas."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import duckdb

from .contracts import ConfigKey, ExecutionEvent


class DuckDBMemoryStore:
    """Persistent store with strict schema versioning."""

    def __init__(self, db_path: Path, schema_version: str) -> None:
        self._db_path = db_path
        self._schema_version = schema_version
        self._conn: duckdb.DuckDBPyConnection | None = None

    def startup(self) -> None:
        """Open DB, bootstrap schema, and validate schema version."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        conn = self._require_conn()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_schema_meta (
                schema_version TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_sessions (
                run_id TEXT PRIMARY KEY,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                mode TEXT,
                batch_size_n INTEGER,
                batch_window_s INTEGER,
                config_hash TEXT,
                git_rev TEXT,
                status TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config_catalog (
                config_id TEXT PRIMARY KEY,
                functions JSON,
                rates JSON,
                config_json JSON,
                n_functions INTEGER,
                sum_rate DOUBLE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_events (
                config_id TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                repetition INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                config_functions JSON,
                config_rates JSON,
                start_ts DOUBLE,
                end_ts DOUBLE,
                duration_s DOUBLE,
                skip_reason TEXT,
                payload_json JSON,
                UNIQUE(config_id, iteration, repetition, run_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS k6_raw_summaries (
                config_id TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                repetition INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                summary_json JSON NOT NULL,
                summary_size_bytes BIGINT,
                ingested_at TIMESTAMP,
                UNIQUE(config_id, iteration, repetition, run_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS policy_updates (
                update_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                records_seen BIGINT,
                score DOUBLE,
                loss DOUBLE,
                ts TIMESTAMP NOT NULL
            )
            """
        )
        self._ensure_schema_meta()

    def schema_version(self) -> str:
        """Return active schema version from DB meta."""
        conn = self._require_conn()
        row = conn.execute(
            "SELECT schema_version FROM memory_schema_meta LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("schema_version not initialized in memory_schema_meta")
        return str(row[0])

    def validate_preload_schema(self, expected_schema_version: str) -> None:
        """Validate loaded schema version against expected value."""
        current = self.schema_version()
        if current != expected_schema_version:
            raise ValueError(
                "schema_version mismatch: "
                f"expected={expected_schema_version} actual={current}"
            )

    def insert_execution_event(self, event: ExecutionEvent) -> None:
        """Insert one execution event and register its config key."""
        conn = self._require_conn()
        functions = list(event.config_key[0])
        rates = list(event.config_key[1])
        payload = {
            "result_row": event.result_row,
            "metrics": event.metrics,
            "summary": event.summary,
        }
        conn.execute(
            """
            INSERT INTO execution_events(
                config_id, iteration, repetition, run_id,
                config_functions, config_rates,
                start_ts, end_ts, duration_s, skip_reason, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            ON CONFLICT(config_id, iteration, repetition, run_id) DO NOTHING
            """,
            [
                event.config_id,
                event.iteration,
                event.repetition,
                event.run_id,
                json.dumps(functions),
                json.dumps(rates),
                event.started_at,
                event.ended_at,
                max(0.0, event.ended_at - event.started_at),
                json.dumps(payload),
            ],
        )
        conn.execute(
            """
            INSERT INTO config_catalog(
                config_id, functions, rates, config_json, n_functions, sum_rate
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(config_id) DO NOTHING
            """,
            [
                event.config_id,
                json.dumps(functions),
                json.dumps(rates),
                json.dumps(
                    {
                        "functions": functions,
                        "rates": rates,
                        "config_pairs": event.config_pairs,
                    }
                ),
                len(functions),
                float(sum(rates)),
            ],
        )

    def load_seen_keys(self) -> set[ConfigKey]:
        """Load previously seen configuration keys from config catalog."""
        conn = self._require_conn()
        rows = conn.execute("SELECT functions, rates FROM config_catalog").fetchall()
        seen: set[ConfigKey] = set()
        for functions_raw, rates_raw in rows:
            functions = tuple(json.loads(str(functions_raw)))
            rates = tuple(int(value) for value in json.loads(str(rates_raw)))
            seen.add((functions, rates))
        return seen

    def count_execution_events(self) -> int:
        """Return number of rows in execution_events."""
        conn = self._require_conn()
        row = conn.execute("SELECT COUNT(*) FROM execution_events").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        """Close DB connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _ensure_schema_meta(self) -> None:
        conn = self._require_conn()
        row = conn.execute("SELECT schema_version FROM memory_schema_meta LIMIT 1").fetchone()
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        if row is None:
            conn.execute(
                "INSERT INTO memory_schema_meta(schema_version, created_at, updated_at) VALUES (?, ?, ?)",
                [self._schema_version, now, now],
            )
            return
        existing = str(row[0])
        if existing != self._schema_version:
            raise ValueError(
                "schema_version mismatch: "
                f"db={existing} configured={self._schema_version}"
            )
        conn.execute("UPDATE memory_schema_meta SET updated_at = ?", [now])

    def _require_conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise RuntimeError("DuckDBMemoryStore.startup() must be called first")
        return self._conn
