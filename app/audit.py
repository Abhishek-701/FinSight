"""Audit log for answers and evidence lineage — sqlite by default, Postgres when DATABASE_URL
is set (app.storage). V6.1: moved off data/audit.jsonl (ephemeral disk on Render, lost on every
redeploy) onto the same DB as sessions/portfolio/watchlist.

`record()` is called today only from the non-streaming chat path with a partial event shape
({session_id, question, contextualized_question, citations, tool_calls, refused}) — request_id,
client_id, and elapsed_ms are not wired in until V6.2, so every field is read with `.get()` and
stored NULL/default when absent.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app import config, storage


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _init_schema(conn: storage._TranslatingConnection) -> None:
    if storage.is_postgres():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS audit ("
            "id BIGSERIAL PRIMARY KEY, created_at TEXT NOT NULL, request_id TEXT, "
            "session_id TEXT, client_id TEXT, question TEXT, contextualized_question TEXT, "
            "refused INTEGER NOT NULL DEFAULT 0, citations TEXT NOT NULL DEFAULT '[]', "
            "tool_calls TEXT NOT NULL DEFAULT '[]', elapsed_ms INTEGER)"
        )
    else:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS audit ("
            "created_at TEXT NOT NULL, request_id TEXT, session_id TEXT, client_id TEXT, "
            "question TEXT, contextualized_question TEXT, refused INTEGER NOT NULL DEFAULT 0, "
            "citations TEXT NOT NULL DEFAULT '[]', tool_calls TEXT NOT NULL DEFAULT '[]', "
            "elapsed_ms INTEGER)"
        )


def _connect() -> storage._TranslatingConnection:
    return storage.connect(config.SESSION_DB_PATH, init=_init_schema)


def record(event: dict) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO audit (created_at, request_id, session_id, client_id, question, "
                "contextualized_question, refused, citations, tool_calls, elapsed_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(),
                    event.get("request_id"),
                    event.get("session_id"),
                    event.get("client_id"),
                    event.get("question"),
                    event.get("contextualized_question"),
                    1 if event.get("refused") else 0,
                    json.dumps(event.get("citations", [])),
                    json.dumps(event.get("tool_calls", [])),
                    event.get("elapsed_ms"),
                ),
            )
    finally:
        conn.close()


def recent(limit: int = 50) -> list[dict]:
    order_col = "id" if storage.is_postgres() else "rowid"
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT created_at, request_id, session_id, client_id, question, "
            "contextualized_question, refused, citations, tool_calls, elapsed_ms "
            f"FROM audit ORDER BY {order_col} DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "created_at": created_at,
            "request_id": request_id,
            "session_id": session_id,
            "client_id": client_id,
            "question": question,
            "contextualized_question": contextualized_question,
            "refused": bool(refused),
            "citations": json.loads(citations),
            "tool_calls": json.loads(tool_calls),
            "elapsed_ms": elapsed_ms,
        }
        for created_at, request_id, session_id, client_id, question, contextualized_question,
        refused, citations, tool_calls, elapsed_ms in rows
    ]


def status() -> dict:
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    finally:
        conn.close()
    return {"backend": storage.backend_name(), "path": str(config.SESSION_DB_PATH), "rows": count}
