from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator, Protocol

import psycopg
from psycopg.rows import dict_row

from app.storage import acquire_file_lock, ensure_runtime_paths, read_state, write_ledger_entry, write_state

DATABASE_URL_ENV = "MASTERS_POOL_DATABASE_URL"
STATE_SCHEMA_VERSION = 2
POLL_LOCK_KEY = 934_221_001
LOOP_LOCK_KEY = 934_221_002


class StateStore(Protocol):
    def read_state(self) -> dict[str, Any]:
        ...

    def write_state(self, state: dict[str, Any]) -> None:
        ...

    def append_ledger(self, entry_type: str, payload: dict[str, Any]) -> None:
        ...

    @contextmanager
    def acquire_poll_lock(self, *, blocking: bool = True) -> Iterator[None]:
        ...

    @contextmanager
    def acquire_loop_lock(self, *, blocking: bool = False) -> Iterator[None]:
        ...


class FileStateStore:
    def __init__(self, base_dir: Path) -> None:
        self.paths = ensure_runtime_paths(base_dir=base_dir)

    def read_state(self) -> dict[str, Any]:
        return read_state(self.paths["state_path"])

    def write_state(self, state: dict[str, Any]) -> None:
        write_state(self.paths["state_path"], state)

    def append_ledger(self, entry_type: str, payload: dict[str, Any]) -> None:
        write_ledger_entry(self.paths["ledger_dir"], entry_type, payload)

    @contextmanager
    def acquire_poll_lock(self, *, blocking: bool = True) -> Iterator[None]:
        with acquire_file_lock(self.paths["poll_lock_path"], blocking=blocking):
            yield

    @contextmanager
    def acquire_loop_lock(self, *, blocking: bool = False) -> Iterator[None]:
        with acquire_file_lock(self.paths["loop_lock_path"], blocking=blocking):
            yield


class PostgresStateStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._ensure_schema()

    def read_state(self) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("SELECT state_json FROM pool_state WHERE id = 1;")
            row = cur.fetchone()
            if not row:
                return {}
            state = row.get("state_json")
            if isinstance(state, dict):
                return state
            return {}

    def write_state(self, state: dict[str, Any]) -> None:
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pool_state (id, state_schema_version, state_json)
                VALUES (1, %s, %s::jsonb)
                ON CONFLICT (id)
                DO UPDATE SET
                  state_schema_version = EXCLUDED.state_schema_version,
                  state_json = EXCLUDED.state_json,
                  updated_at = NOW();
                """,
                (STATE_SCHEMA_VERSION, json.dumps(state)),
            )
            conn.commit()

    def append_ledger(self, entry_type: str, payload: dict[str, Any]) -> None:
        payload_json = json.dumps(payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pool_ledger (entry_type, payload_hash, payload)
                VALUES (%s, %s, %s::jsonb);
                """,
                (entry_type, payload_hash, payload_json),
            )
            conn.commit()

    @contextmanager
    def acquire_poll_lock(self, *, blocking: bool = True) -> Iterator[None]:
        with self._advisory_lock(POLL_LOCK_KEY, blocking=blocking):
            yield

    @contextmanager
    def acquire_loop_lock(self, *, blocking: bool = False) -> Iterator[None]:
        with self._advisory_lock(LOOP_LOCK_KEY, blocking=blocking):
            yield

    def _ensure_schema(self) -> None:
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pool_state (
                  id SMALLINT PRIMARY KEY,
                  state_schema_version INTEGER NOT NULL,
                  state_json JSONB NOT NULL,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pool_ledger (
                  id BIGSERIAL PRIMARY KEY,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  entry_type TEXT NOT NULL,
                  payload_hash TEXT NOT NULL,
                  payload JSONB NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pool_ledger_created_at
                ON pool_ledger (created_at DESC);
                """
            )
            conn.commit()

    @contextmanager
    def _advisory_lock(self, key: int, *, blocking: bool) -> Iterator[None]:
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cur:
            if blocking:
                cur.execute("SELECT pg_advisory_lock(%s);", (key,))
            else:
                cur.execute("SELECT pg_try_advisory_lock(%s);", (key,))
                row = cur.fetchone()
                if not row or row[0] is not True:
                    raise RuntimeError(f"Lock already held: advisory:{key}")
            try:
                yield
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s);", (key,))
                conn.commit()


def create_state_store(base_dir: Path) -> StateStore:
    database_url = os.getenv(DATABASE_URL_ENV, "").strip()
    if database_url:
        return PostgresStateStore(database_url=database_url)
    return FileStateStore(base_dir=base_dir)
