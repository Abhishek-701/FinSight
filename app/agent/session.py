"""Chat session store — sqlite by default, Postgres when DATABASE_URL is set (app.storage)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app import config, storage


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _init_schema(conn: storage._TranslatingConnection) -> None:
    # sqlite always has an implicit `rowid` to order by; Postgres doesn't, so its table gets an
    # explicit auto-incrementing id instead. This only affects new tables/backends — sqlite's
    # existing on-disk schema (no `id` column) needs no migration since rowid already works.
    if storage.is_postgres():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "id BIGSERIAL PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, "
            "content TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
    else:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, "
            "metadata TEXT NOT NULL, created_at TEXT NOT NULL)"
        )


def _connect() -> storage._TranslatingConnection:
    return storage.connect(config.SESSION_DB_PATH, init=_init_schema)


def new_session_id() -> str:
    return uuid.uuid4().hex


def append(session_id: str, role: str, content: str, metadata: dict | None = None) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, json.dumps(metadata or {}), _now()),
            )
    finally:
        conn.close()


def history(session_id: str, limit: int = 20) -> list[dict]:
    order_col = "id" if storage.is_postgres() else "rowid"
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT role, content, metadata, created_at FROM messages "
            f"WHERE session_id = ? ORDER BY {order_col} DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"role": role, "content": content, "metadata": json.loads(metadata), "created_at": created_at}
        for role, content, metadata, created_at in reversed(rows)
    ]


def status() -> dict:
    path: Path = config.SESSION_DB_PATH
    return {"backend": storage.backend_name(), "path": str(path), "exists": path.exists()}
