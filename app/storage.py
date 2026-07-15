"""Storage backend selection: sqlite (default, local file) or Postgres (DATABASE_URL set).

Only app/agent/session.py, app/portfolio.py, and app/watchlist.py use this — small
per-client_id/session tables. The filing corpus (chunks/facts/Chroma) stays on disk either way;
this only affects sessions, portfolio holdings, and watchlists, which matters on Render's free
tier because sqlite there lives on ephemeral disk and resets on redeploy.

Kept deliberately thin: callers keep writing ordinary `?`-placeholder SQL exactly like the
sqlite3 driver always required. connect() returns a connection whose .execute() translates
`?` to `%s` transparently when running on Postgres, so the three call sites don't need two SQL
dialects for the common case. `ON CONFLICT ... DO UPDATE SET x = excluded.x` (portfolio.py's
upsert) is already valid, unchanged, on both engines. The two things that genuinely differ —
column introspection for an idempotent migration, and insert-or-ignore — get a small dialect
branch at their one or two call sites (sqlite_columns() / insert_ignore() below), not a bigger
abstraction than the problem needs.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app import config


def is_postgres() -> bool:
    return bool(config.DATABASE_URL)


def backend_name() -> str:
    return "postgres" if is_postgres() else "sqlite"


class _TranslatingCursor:
    def __init__(self, cursor: Any, translate: bool) -> None:
        self._cursor = cursor
        self._translate = translate

    def execute(self, sql: str, params: tuple = ()) -> "_TranslatingCursor":
        self._cursor.execute(sql.replace("?", "%s") if self._translate else sql, params)
        return self

    def fetchall(self) -> list:
        return self._cursor.fetchall()

    def fetchone(self) -> Any:
        return self._cursor.fetchone()


class _TranslatingConnection:
    """Uniform enough surface for our usage: .execute() returns a cursor-like object, and the
    connection is usable as a `with conn:` block (commits on clean exit, rolls back on error) —
    matching sqlite3.Connection's own context-manager semantics, which the DDL/migration calls
    below rely on to make sure CREATE TABLE/ALTER TABLE are actually committed on Postgres
    (sqlite3 auto-commits DDL outside a transaction; psycopg does not).
    """

    def __init__(self, conn: Any, translate: bool) -> None:
        self._conn = conn
        self.translate = translate

    def execute(self, sql: str, params: tuple = ()) -> _TranslatingCursor:
        return _TranslatingCursor(self._conn.cursor(), self.translate).execute(sql, params)

    def __enter__(self) -> "_TranslatingConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False

    def close(self) -> None:
        self._conn.close()


def connect(
    sqlite_path: Path, init: Callable[[_TranslatingConnection], None] | None = None,
) -> _TranslatingConnection:
    """Open a connection: Postgres if DATABASE_URL is set, else sqlite at `sqlite_path` (the
    existing local default, untouched). `init`, if given, runs once per connection wrapped in
    its own committed transaction — the schema-creation/migration callback each caller passes.
    """
    if is_postgres():
        import psycopg

        conn = _TranslatingConnection(psycopg.connect(config.DATABASE_URL), translate=True)
    else:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = _TranslatingConnection(sqlite3.connect(sqlite_path), translate=False)
    if init:
        with conn:
            init(conn)
    return conn


def sqlite_columns(conn: _TranslatingConnection, table: str) -> list[str]:
    """Column names via PRAGMA table_info — sqlite only. Postgres supports `ADD COLUMN IF NOT
    EXISTS` natively, so callers only need this in the sqlite branch of a migration check."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def insert_ignore(table: str, columns: tuple[str, ...], conflict_cols: tuple[str, ...]) -> str:
    """INSERT that no-ops on a conflicting primary key: `OR IGNORE` on sqlite, `ON CONFLICT ...
    DO NOTHING` on Postgres. `columns` order must match the values tuple passed to execute()."""
    cols = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    if is_postgres():
        conflict = ", ".join(conflict_cols)
        return f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT ({conflict}) DO NOTHING"
    return f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})"
