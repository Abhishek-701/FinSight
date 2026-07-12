"""Small SQLite-backed portfolio store, keyed by anonymous client_id. Shares only — dollar
amounts are converted to shares client-side at the live price before this module sees them.

analyze() (V4.3) adds live valuation/P&L/concentration on top of the plain holdings list —
average-cost basis, no lot tracking (a single cost_basis per ticker, overwritten on each
set_holding call, same "last write wins" semantics as shares already had)."""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import UTC, datetime

from app import config, universe
from app.tools import market

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


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
    # Idempotent migration: NULL cost_basis means "not provided", not zero — P&L stays honestly
    # unavailable rather than assumed. Pre-V4.3 rows get NULL automatically.
    cols = [row[1] for row in conn.execute("PRAGMA table_info(portfolio)").fetchall()]
    if "cost_basis" not in cols:
        conn.execute("ALTER TABLE portfolio ADD COLUMN cost_basis REAL")
    return conn


def _row(ticker: str, shares: float, cost_basis: float | None, updated_at: str) -> dict:
    return {
        "ticker": ticker,
        "company": universe.company_name(ticker),
        "shares": shares,
        "cost_basis": cost_basis,
        "updated_at": updated_at,
    }


def set_holding(
    client_id: str, ticker: str, shares: float, cost_basis: float | None = None
) -> list[dict]:
    ticker = ticker.upper()
    # Format-only validation: a portfolio can hold any real ticker, not just ingested/covered
    # companies — quotes work regardless of filing coverage (same "*" openness as market_quote).
    if not _TICKER_RE.match(ticker):
        raise ValueError("unsupported_ticker")
    if not math.isfinite(shares) or shares <= 0 or shares > 1e9:
        raise ValueError("invalid_shares")
    if cost_basis is not None and (not math.isfinite(cost_basis) or cost_basis <= 0 or cost_basis > 1e9):
        raise ValueError("invalid_cost_basis")
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO portfolio (client_id, ticker, shares, cost_basis, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(client_id, ticker) DO UPDATE SET shares = excluded.shares, "
                "cost_basis = excluded.cost_basis, updated_at = excluded.updated_at",
                (client_id, ticker, shares, cost_basis, _now()),
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
            "SELECT ticker, shares, cost_basis, updated_at FROM portfolio "
            "WHERE client_id = ? ORDER BY updated_at",
            (client_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row(ticker, shares, cost_basis, updated_at) for ticker, shares, cost_basis, updated_at in rows]


def status() -> dict:
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    finally:
        conn.close()
    return {"path": str(config.SESSION_DB_PATH), "rows": count}


def _hhi_band(hhi: float) -> str:
    """Standard antitrust-style HHI bands (0-10000 scale, sum of squared percentage shares)."""
    if hhi < 1500:
        return "diversified"
    if hhi < 2500:
        return "moderately concentrated"
    return "concentrated"


def analyze(client_id: str) -> dict:
    """Live valuation, P&L (where cost_basis is known), and concentration for one portfolio.

    Degrades gracefully per-holding: a quote failure zeroes that holding's contribution to
    totals/weights (market_status="unavailable") rather than failing the whole analysis.
    """
    holdings = items(client_id)
    as_of = _now()
    if not holdings:
        return {
            "client_id": client_id, "as_of": as_of, "holdings": [],
            "total_value": 0.0, "total_day_change": None, "total_unrealized_pl": None,
            "concentration": None, "disclaimer": config.MARKET_DISCLAIMER,
        }

    priced: list[dict] = []
    for h in holdings:
        quote = market.market_quote(h["ticker"])
        data = quote.get("data") if quote["status"] == "ok" else None
        price = data.get("price") if data else None
        # market.py's change_percent is already percentage-scaled (-0.28 means -0.28%); every
        # other *_pct/weight field here is a 0-1 FRACTION (weight, unrealized_pl_pct) — divide
        # by 100 at this boundary so downstream formatting has one consistent convention.
        raw_change_pct = data.get("change_percent") if data else None
        change_pct = (raw_change_pct / 100) if raw_change_pct is not None else None
        change = data.get("change") if data else None
        value = h["shares"] * price if price is not None else None
        cost_basis = h["cost_basis"]
        unrealized_pl = (value - h["shares"] * cost_basis) if value is not None and cost_basis else None
        unrealized_pl_pct = ((price - cost_basis) / cost_basis) if price is not None and cost_basis else None
        day_change_value = h["shares"] * change if change is not None else None
        priced.append({
            **h,
            "price": price,
            "value": value,
            "day_change_pct": change_pct,
            "day_change_value": day_change_value,
            "unrealized_pl": unrealized_pl,
            "unrealized_pl_pct": unrealized_pl_pct,
            "market_status": "ok" if price is not None else "unavailable",
        })

    total_value = sum(p["value"] for p in priced if p["value"] is not None)
    for p in priced:
        p["weight"] = (p["value"] / total_value) if p["value"] is not None and total_value else None

    priced_with_value = [p for p in priced if p["value"] is not None]
    total_day_change = sum(p["day_change_value"] for p in priced_with_value if p["day_change_value"] is not None) or None
    pl_known = [p for p in priced if p["unrealized_pl"] is not None]
    total_unrealized_pl = sum(p["unrealized_pl"] for p in pl_known) if pl_known else None

    concentration = None
    if total_value:
        weights_pct = sorted((p["weight"] * 100 for p in priced_with_value), reverse=True)
        hhi = sum(w * w for w in weights_pct)
        concentration = {
            "top_ticker": max(priced_with_value, key=lambda p: p["weight"])["ticker"],
            "top_weight": weights_pct[0] / 100,
            "top3_weight": sum(weights_pct[:3]) / 100,
            "hhi": round(hhi, 1),
            "band": _hhi_band(hhi),
        }

    return {
        "client_id": client_id, "as_of": as_of, "holdings": priced,
        "total_value": total_value, "total_day_change": total_day_change,
        "total_unrealized_pl": total_unrealized_pl, "concentration": concentration,
        "disclaimer": config.MARKET_DISCLAIMER,
    }
