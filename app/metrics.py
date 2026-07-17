"""Per-request metrics store — sqlite by default, Postgres when DATABASE_URL is set
(app.storage). New in V6.1: table + writer + tests land now so the Postgres DDL ships once;
nothing calls `record()` yet — the request-logging middleware starts writing rows in V6.2 once
app/obs.py exists to capture LLM token usage per request.
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
            "CREATE TABLE IF NOT EXISTS request_metrics ("
            "id BIGSERIAL PRIMARY KEY, created_at TEXT NOT NULL, request_id TEXT NOT NULL, "
            "method TEXT NOT NULL, route TEXT NOT NULL, status_code INTEGER NOT NULL, "
            "elapsed_ms INTEGER NOT NULL, client_id TEXT, llm_calls INTEGER NOT NULL DEFAULT 0, "
            "input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, "
            "embed_tokens INTEGER NOT NULL DEFAULT 0, models TEXT NOT NULL DEFAULT '{}', "
            "refused INTEGER, error TEXT)"
        )
    else:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS request_metrics ("
            "created_at TEXT NOT NULL, request_id TEXT NOT NULL, method TEXT NOT NULL, "
            "route TEXT NOT NULL, status_code INTEGER NOT NULL, elapsed_ms INTEGER NOT NULL, "
            "client_id TEXT, llm_calls INTEGER NOT NULL DEFAULT 0, "
            "input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, "
            "embed_tokens INTEGER NOT NULL DEFAULT 0, models TEXT NOT NULL DEFAULT '{}', "
            "refused INTEGER, error TEXT)"
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_request_metrics_created ON request_metrics (created_at)")


def _connect() -> storage._TranslatingConnection:
    return storage.connect(config.SESSION_DB_PATH, init=_init_schema)


def record(row: dict) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO request_metrics (created_at, request_id, method, route, "
                "status_code, elapsed_ms, client_id, llm_calls, input_tokens, output_tokens, "
                "embed_tokens, models, refused, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(),
                    row["request_id"],
                    row["method"],
                    row["route"],
                    row["status_code"],
                    row["elapsed_ms"],
                    row.get("client_id"),
                    row.get("llm_calls", 0),
                    row.get("input_tokens", 0),
                    row.get("output_tokens", 0),
                    row.get("embed_tokens", 0),
                    json.dumps(row.get("models", {})),
                    None if row.get("refused") is None else (1 if row["refused"] else 0),
                    row.get("error"),
                ),
            )
    finally:
        conn.close()


def _deserialize(row: tuple) -> dict:
    (created_at, request_id, method, route, status_code, elapsed_ms, client_id, llm_calls,
     input_tokens, output_tokens, embed_tokens, models, refused, error) = row
    return {
        "created_at": created_at,
        "request_id": request_id,
        "method": method,
        "route": route,
        "status_code": status_code,
        "elapsed_ms": elapsed_ms,
        "client_id": client_id,
        "llm_calls": llm_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "embed_tokens": embed_tokens,
        "models": json.loads(models),
        "refused": None if refused is None else bool(refused),
        "error": error,
    }


def recent(limit: int = 50) -> list[dict]:
    order_col = "id" if storage.is_postgres() else "rowid"
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT created_at, request_id, method, route, status_code, elapsed_ms, client_id, "
            "llm_calls, input_tokens, output_tokens, embed_tokens, models, refused, error "
            f"FROM request_metrics ORDER BY {order_col} DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [_deserialize(row) for row in rows]


def window(since_iso: str) -> list[dict]:
    """All rows with created_at >= since_iso (ISO-8601 UTC string) — used by the V6.4 admin
    aggregates, which compute per-day buckets and p50/p95 in Python over the returned rows."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT created_at, request_id, method, route, status_code, elapsed_ms, client_id, "
            "llm_calls, input_tokens, output_tokens, embed_tokens, models, refused, error "
            "FROM request_metrics WHERE created_at >= ?",
            (since_iso,),
        ).fetchall()
    finally:
        conn.close()
    return [_deserialize(row) for row in rows]


def status() -> dict:
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM request_metrics").fetchone()[0]
    finally:
        conn.close()
    return {"backend": storage.backend_name(), "path": str(config.SESSION_DB_PATH), "rows": count}
