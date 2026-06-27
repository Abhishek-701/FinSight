"""Small SQLite-backed chat session store."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app import config


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    config.SESSION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.SESSION_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, "
        "metadata TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    return conn


def new_session_id() -> str:
    return uuid.uuid4().hex


def append(session_id: str, role: str, content: str, metadata: dict | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(metadata or {}), _now()),
        )


def history(session_id: str, limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content, metadata, created_at FROM messages "
            "WHERE session_id = ? ORDER BY rowid DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [
        {"role": role, "content": content, "metadata": json.loads(metadata), "created_at": created_at}
        for role, content, metadata, created_at in reversed(rows)
    ]


def status() -> dict:
    path: Path = config.SESSION_DB_PATH
    return {"path": str(path), "exists": path.exists()}
