"""Small SQLite-backed portfolio store, keyed by anonymous client_id. Shares only — dollar
amounts are converted to shares client-side at the live price before this module sees them."""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime

from app import config, universe


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    config.SESSION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.SESSION_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS portfolio ("
        "client_id TEXT NOT NULL, ticker TEXT NOT NULL, shares REAL NOT NULL, "
        "updated_at TEXT NOT NULL, PRIMARY KEY (client_id, ticker))"
    )
    return conn


def _row(ticker: str, shares: float, updated_at: str) -> dict:
    return {
        "ticker": ticker,
        "company": universe.company_name(ticker),
        "shares": shares,
        "updated_at": updated_at,
    }


def set_holding(client_id: str, ticker: str, shares: float) -> list[dict]:
    ticker = ticker.upper()
    if ticker not in universe.active_companies():
        raise ValueError("unsupported_ticker")
    if not math.isfinite(shares) or shares <= 0 or shares > 1e9:
        raise ValueError("invalid_shares")
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO portfolio (client_id, ticker, shares, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(client_id, ticker) DO UPDATE SET shares = excluded.shares, "
                "updated_at = excluded.updated_at",
                (client_id, ticker, shares, _now()),
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
                "DELETE FROM portfolio WHERE client_id = ? AND ticker = ?",
                (client_id, ticker),
            )
    finally:
        conn.close()
    return items(client_id)


def items(client_id: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT ticker, shares, updated_at FROM portfolio WHERE client_id = ? ORDER BY updated_at",
            (client_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row(ticker, shares, updated_at) for ticker, shares, updated_at in rows]


def status() -> dict:
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    finally:
        conn.close()
    return {"path": str(config.SESSION_DB_PATH), "rows": count}
