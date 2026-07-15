"""Portfolio store, keyed by anonymous client_id — sqlite by default, Postgres when
DATABASE_URL is set (app.storage). Shares only — dollar amounts are converted to shares
client-side at the live price before this module sees them.

analyze() (V4.3) adds live valuation/P&L/concentration on top of the plain holdings list —
average-cost basis, no lot tracking (a single cost_basis per ticker, overwritten on each
set_holding call, same "last write wins" semantics as shares already had)."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from app import config, storage, universe
from app.tools import market

_WHATIF_SHARES_RE = re.compile(
    r"what\s+if\s+i\s+(bought|buy|added?|sold|sell|trimmed|trim)\s+(\d+(?:\.\d+)?)\s+(?:more\s+)?"
    r"shares?\s+of\s+([A-Za-z]{1,6})\b", re.I,
)
_WHATIF_TOP_HOLDING_RE = re.compile(
    r"what\s+if\s+i\s+(doubled|double|halved|halve|trimmed|trim).{0,30}\btop\s+holding\b", re.I,
)

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _init_schema(conn: storage._TranslatingConnection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS portfolio ("
        "client_id TEXT NOT NULL, ticker TEXT NOT NULL, shares REAL NOT NULL, "
        "updated_at TEXT NOT NULL, PRIMARY KEY (client_id, ticker))"
    )
    # Idempotent migration: NULL cost_basis means "not provided", not zero — P&L stays honestly
    # unavailable rather than assumed. Pre-V4.3 rows get NULL automatically. Postgres supports
    # ADD COLUMN IF NOT EXISTS natively; sqlite doesn't, so it checks first via PRAGMA.
    if storage.is_postgres():
        conn.execute("ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS cost_basis REAL")
    elif "cost_basis" not in storage.sqlite_columns(conn, "portfolio"):
        conn.execute("ALTER TABLE portfolio ADD COLUMN cost_basis REAL")


def _connect() -> storage._TranslatingConnection:
    return storage.connect(config.SESSION_DB_PATH, init=_init_schema)


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
    return {"backend": storage.backend_name(), "path": str(config.SESSION_DB_PATH), "rows": count}


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
    return _price_holdings(client_id, items(client_id), _now())


def _price_holdings(client_id: str, holdings: list[dict], as_of: str) -> dict:
    """Shared pricing/concentration math behind analyze() and whatif()'s before/after scenarios.
    Takes an explicit holdings list (not read from the DB) so whatif() can price a hypothetical
    set of holdings without touching storage.
    """
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


def whatif(client_id: str, trades: list[dict]) -> dict:
    """Simulate hypothetical share deltas on top of current holdings — never persisted.

    trades: [{"ticker": str, "delta_shares": float}], positive to add, negative to trim/sell.
    A ticker not currently held is only added to the "after" scenario when its delta is
    positive; a holding whose shares net to ~0 or below is dropped from "after" (fully sold).
    """
    as_of = _now()
    current = items(client_id)
    by_ticker = {h["ticker"]: dict(h) for h in current}
    for t in trades:
        ticker = t["ticker"].upper()
        if not _TICKER_RE.match(ticker):
            raise ValueError("unsupported_ticker")
        delta = t["delta_shares"]
        if not math.isfinite(delta) or delta == 0 or abs(delta) > 1e9:
            raise ValueError("invalid_delta_shares")
        if ticker in by_ticker:
            by_ticker[ticker]["shares"] += delta
        elif delta > 0:
            by_ticker[ticker] = {
                "ticker": ticker, "company": universe.company_name(ticker),
                "shares": delta, "cost_basis": None, "updated_at": as_of,
            }
    hypothetical = [h for h in by_ticker.values() if h["shares"] > 1e-9]
    before = _price_holdings(client_id, current, as_of)
    after = _price_holdings(client_id, hypothetical, as_of)
    return {"client_id": client_id, "as_of": as_of, "trades": trades, "before": before, "after": after}


def parse_whatif_trades(question: str, client_id: str) -> list[dict] | None:
    """Deterministic NLU for the narrow what-if phrasings the chat UI supports. Returns None
    when the question doesn't match a recognized pattern — the caller turns that into a
    clarifying refusal rather than guessing at a trade.
    """
    m = _WHATIF_SHARES_RE.search(question)
    if m:
        verb, qty, ticker = m.group(1).lower(), float(m.group(2)), m.group(3).upper()
        sign = -1 if verb in ("sold", "sell", "trimmed", "trim") else 1
        return [{"ticker": ticker, "delta_shares": sign * qty}]

    m = _WHATIF_TOP_HOLDING_RE.search(question)
    if m:
        analysis = analyze(client_id)
        priced_holdings = [h for h in analysis["holdings"] if h["value"] is not None]
        if not priced_holdings:
            return None
        top = max(priced_holdings, key=lambda h: h["value"])
        verb = m.group(1).lower()
        if verb in ("doubled", "double"):
            return [{"ticker": top["ticker"], "delta_shares": top["shares"]}]
        return [{"ticker": top["ticker"], "delta_shares": -top["shares"] / 2}]

    return None


def benchmark(client_id: str, period: str = "3mo") -> dict:
    """Portfolio value history (today's shares held constant across the period — no
    rebalancing, so this is NOT a historical-weights-accurate backtest) vs SPY over the
    same period. Caps the fan-out to the top BENCHMARK_MAX_HOLDINGS holdings by current value.
    """
    holdings = items(client_id)
    if not holdings:
        return {"client_id": client_id, "period": period, "portfolio": None, "spy": None,
                "holdings_used": [], "disclaimer": config.MARKET_DISCLAIMER}

    priced = analyze(client_id)
    top_by_value = sorted(
        (h for h in priced["holdings"] if h["value"] is not None),
        key=lambda h: h["value"], reverse=True,
    )[: config.BENCHMARK_MAX_HOLDINGS]
    shares_by_ticker = {h["ticker"]: h["shares"] for h in top_by_value}

    histories: dict[str, list[dict]] = {}
    for ticker in shares_by_ticker:
        result = market.market_history(ticker, period)
        if result["status"] == "ok" and result["data"]["rows"]:
            histories[ticker] = result["data"]["rows"]

    spy_result = market.market_history("SPY", period)
    spy_rows = spy_result["data"]["rows"] if spy_result["status"] == "ok" else []

    if not histories:
        return {"client_id": client_id, "period": period, "portfolio": None,
                "spy": spy_rows or None, "holdings_used": [], "disclaimer": config.MARKET_DISCLAIMER}

    # Align on dates common to every included holding so the weighted sum never silently
    # drops a holding's contribution for a date it happens to be missing.
    common_dates: set[str] | None = None
    for rows in histories.values():
        dates = {r["date"] for r in rows}
        common_dates = dates if common_dates is None else (common_dates & dates)
    sorted_dates = sorted(common_dates or set())

    by_date_close = {t: {r["date"]: r["close"] for r in rows} for t, rows in histories.items()}
    portfolio_rows = []
    for date in sorted_dates:
        value = sum(shares_by_ticker[t] * by_date_close[t][date] for t in histories)
        portfolio_rows.append({"date": date, "open": value, "high": value, "low": value,
                                "close": value, "volume": 0})

    return {
        "client_id": client_id, "period": period,
        "portfolio": portfolio_rows, "spy": spy_rows or None,
        "holdings_used": sorted(histories), "disclaimer": config.MARKET_DISCLAIMER,
    }
