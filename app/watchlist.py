"""Small SQLite-backed watchlist store, keyed by anonymous client_id."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from app import config, universe


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    config.SESSION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.SESSION_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS watchlist ("
        "client_id TEXT NOT NULL, ticker TEXT NOT NULL, added_at TEXT NOT NULL, "
        "PRIMARY KEY (client_id, ticker))"
    )
    return conn


def _row(ticker: str, added_at: str) -> dict:
    return {"ticker": ticker, "company": universe.company_name(ticker), "added_at": added_at}


def add(client_id: str, ticker: str) -> list[dict]:
    ticker = ticker.upper()
    if ticker not in universe.active_companies():
        raise ValueError("unsupported_ticker")
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist VALUES (?, ?, ?)",
                (client_id, ticker, _now()),
            )
    finally:
        conn.close()
    return items(client_id)


def remove(client_id: str, ticker: str) -> list[dict]:
    ticker = ticker.upper()
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "DELETE FROM watchlist WHERE client_id = ? AND ticker = ?",
                (client_id, ticker),
            )
    finally:
        conn.close()
    return items(client_id)


def items(client_id: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT ticker, added_at FROM watchlist WHERE client_id = ? ORDER BY added_at",
            (client_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row(ticker, added_at) for ticker, added_at in rows]


def status() -> dict:
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    finally:
        conn.close()
    return {"path": str(config.SESSION_DB_PATH), "rows": count}
