"""Company Insight Brief — fuses live market data with XBRL fundamentals and filing RAG.

Phase 2 (this file, partial): build_brief_data() assembles the deterministic card —
quote, price trend, valuation ratios, screener ranks — as a chat tool (company_insight)
and as the data half of the /api/insight endpoints. Phase 3 adds the narrative sections
(brief/stream_brief) on top of the same deterministic data.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app import config, facts, screener, synthesize
from app.tools import compute, market


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _screener_rank_context(ticker: str) -> dict[str, dict]:
    """Per-metric rank of `ticker` among all six companies, XBRL-only (no extra quotes)."""
    rows = screener.snapshot(include_market=False)["rows"]
    ranks: dict[str, dict] = {}
    for metric in ("operating_margin", "net_margin", "revenue_growth_yoy", "roe"):
        ranked = screener.rank(metric, order="desc", rows=rows)
        present = [r for r in ranked if r.get(metric) is not None]
        for position, row in enumerate(present, start=1):
            if row["ticker"] == ticker:
                ranks[metric] = {"rank": position, "of": len(present), "value": row[metric]}
                break
    return ranks


def build_brief_data(ticker: str) -> dict:
    """Assemble the deterministic insight card: quote, history, fundamentals, valuation, ranks.

    Degrades gracefully when yfinance is unavailable: fundamentals/ranks still populate from
    XBRL, valuation is omitted, and market_status reports "unavailable".
    """
    ticker = ticker.upper()
    company = config.COMPANIES.get(ticker, ticker)
    evidence: list[dict] = []

    quote_result = market.market_quote(ticker)
    history_result = market.market_history(ticker, config.INSIGHT_HISTORY_PERIOD)
    market_status = "ok" if quote_result["status"] == "ok" else "unavailable"
    quote_data = quote_result.get("data") if quote_result["status"] == "ok" else None
    history_data = history_result.get("data") if history_result["status"] == "ok" else None
    evidence.extend(quote_result.get("evidence", []))
    evidence.extend(history_result.get("evidence", []))

    fundamentals = screener.row(ticker, include_market=False)
    ranks = _screener_rank_context(ticker)

    xbrl_facts = []
    recent_rev, prior_rev = facts.query_yoy("revenue", ticker)
    for f in (recent_rev, prior_rev):
        if f:
            xbrl_facts.append(f)
    eps_fact = facts.query("eps_diluted", ticker)
    if eps_fact:
        xbrl_facts.append(eps_fact)
    xbrl_chunk = None
    if xbrl_facts:
        _, xbrl_chunks = synthesize.build_xbrl_context(xbrl_facts)
        if xbrl_chunks:
            xbrl_chunk = xbrl_chunks[0]
            evidence.append(xbrl_chunk)

    valuation: dict = {}
    if market_status == "ok":
        compute_evidence = evidence  # quote + xbrl chunks already collected
        pe = compute.compute_metric("pe_ratio", evidence=compute_evidence)
        if pe["status"] == "ok":
            valuation["pe_ratio"] = pe["data"]
            evidence.extend(pe["evidence"])
        ps = compute.compute_metric("ps_ratio", evidence=compute_evidence)
        if ps["status"] == "ok":
            valuation["ps_ratio"] = ps["data"]
            evidence.extend(ps["evidence"])
    if history_data and history_data.get("rows"):
        change = compute.compute_metric("price_change", evidence=history_result.get("evidence", []))
        if change["status"] == "ok":
            valuation["price_change"] = change["data"]
            evidence.extend(change["evidence"])

    return {
        "ticker": ticker,
        "company": company,
        "as_of": _now_iso(),
        "quote": quote_data,
        "history": history_data,
        "fundamentals": fundamentals,
        "valuation": valuation,
        "ranks": ranks,
        "disclaimer": config.MARKET_DISCLAIMER,
        "evidence": evidence,
        "market_status": market_status,
    }


def company_insight(ticker: str | None = None, question: str | None = None,
                    route: dict | None = None, **_: object) -> dict:
    """Chat tool: assemble the insight card and return it as citable evidence."""
    ticker = ticker or ((route or {}).get("tickers") or [None])[0]
    if not ticker or ticker.upper() not in config.COMPANIES:
        return {"status": "missing_ticker", "data": {}, "evidence": []}
    data = build_brief_data(ticker)
    return {
        "status": "ok",
        "data": {"valuation": data["valuation"], "ranks": data["ranks"],
                 "market_status": data["market_status"]},
        "evidence": data["evidence"],
    }
