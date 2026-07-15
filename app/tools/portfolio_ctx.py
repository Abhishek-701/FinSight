"""portfolio_context tool — the only tool whose primary argument (client_id) is injected
server-side by the executor, never chosen by the LLM or the deterministic router (see
app/agent/executor.py). A plan can decide WHETHER to call this tool; it can never decide
WHOSE portfolio it reads.

Builds one PORT-{client8}-{stamp} evidence chunk (holdings, weights, P&L, concentration —
app.portfolio.analyze() already does the live-quote fan-out) plus, if the portfolio is
non-empty, a -NEWS- chunk (via the existing news_headlines tool) for the two holdings with
the largest absolute day-move — one tool call from the plan's perspective, several internal
data pulls, matching the market/facts pattern already used elsewhere.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app import config, portfolio, retrieve, universe
from app.tools import news as news_tool

_TOP_MOVERS_FOR_NEWS = 2
_BENCHMARK_RE = re.compile(config.BENCHMARK_RE, re.I)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _refusal_meta(route: dict | None, reason: str, message: str) -> dict:
    return {
        "route": route or {}, "sub_queries": [], "retrieval": [],
        "answer": message, "citations": [], "gaps": [],
        "refused": True, "refusal_reason": reason,
    }


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "unavailable"


def _fmt_money(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "unavailable"


def build_portfolio_chunk(analysis: dict) -> dict:
    client_id = analysis["client_id"]
    as_of = analysis["as_of"]
    stamp = as_of.replace("+00:00", "Z").replace("-", "").replace(":", "")
    chunk_id = f"PORT-{client_id[:8]}-{stamp}"

    lines = [
        f"Portfolio as of {as_of}: {len(analysis['holdings'])} holdings, "
        f"total value {_fmt_money(analysis['total_value'])}."
    ]
    if analysis["total_day_change"] is not None:
        lines.append(f"Total day change: {_fmt_money(analysis['total_day_change'])}.")
    if analysis["total_unrealized_pl"] is not None:
        lines.append(f"Total unrealized P&L (holdings with a cost basis entered): "
                      f"{_fmt_money(analysis['total_unrealized_pl'])}.")
    else:
        lines.append("Total unrealized P&L: not available (no cost basis entered for any holding).")

    for h in analysis["holdings"]:
        if h["market_status"] != "ok":
            lines.append(f"- {h['ticker']} ({h['company']}): {h['shares']} shares — "
                         f"live price unavailable.")
            continue
        pl_text = (
            f"unrealized P&L {_fmt_money(h['unrealized_pl'])} ({_fmt_pct(h['unrealized_pl_pct'])})"
            if h["unrealized_pl"] is not None else "unrealized P&L not available (no cost basis entered)"
        )
        lines.append(
            f"- {h['ticker']} ({h['company']}): {h['shares']} shares @ {_fmt_money(h['price'])} = "
            f"{_fmt_money(h['value'])} ({_fmt_pct(h['weight'])} of portfolio), "
            f"day change {_fmt_pct(h['day_change_pct'])}, {pl_text}."
        )

    conc = analysis["concentration"]
    if conc:
        lines.append(
            f"Concentration: top holding {conc['top_ticker']} is {_fmt_pct(conc['top_weight'])} "
            f"of the portfolio; top 3 holdings are {_fmt_pct(conc['top3_weight'])}; "
            f"HHI={conc['hhi']} ({conc['band']})."
        )

    text = (
        f"[Portfolio] Anonymous client holdings snapshot (not a company filing or market "
        f"quote — this is the user's own saved holdings)\n" + "\n".join(lines)
    )
    return {
        "chunk_id": chunk_id,
        "ticker": None,
        "company": "Your Portfolio",
        "item": "Portfolio",
        "section_title": "Holdings Snapshot",
        "filing_date": as_of,
        "fused_score": 1.0,
        "text": text,
        "kind": "portfolio",
        "as_of": as_of,
        "data": analysis,
    }


def _top_movers(analysis: dict, n: int) -> list[str]:
    priced = [h for h in analysis["holdings"] if h["market_status"] == "ok" and h["day_change_pct"] is not None]
    ranked = sorted(priced, key=lambda h: abs(h["day_change_pct"]), reverse=True)
    return [h["ticker"] for h in ranked[:n]]


def _benchmark_line(client_id: str) -> str | None:
    """One-line vs-SPY summary, only computed when the question actually asks for it (see
    _BENCHMARK_RE below) — this is an extra market_history fan-out per included holding plus
    SPY, so it's not worth paying on every portfolio turn.
    """
    bench = portfolio.benchmark(client_id, "3mo")
    port_rows, spy_rows = bench.get("portfolio"), bench.get("spy")
    if not port_rows or len(port_rows) < 2 or not spy_rows or len(spy_rows) < 2:
        return None
    port_ret = (port_rows[-1]["close"] - port_rows[0]["close"]) / port_rows[0]["close"] * 100
    spy_ret = (spy_rows[-1]["close"] - spy_rows[0]["close"]) / spy_rows[0]["close"] * 100
    return (
        f"Over the past 3 months, applying today's holdings/weights backward (static, no "
        f"rebalancing), this portfolio would have changed {port_ret:+.1f}% vs SPY {spy_ret:+.1f}%."
    )


def portfolio_context(
    client_id: str | None = None, question: str | None = None, route: dict | None = None, **_: Any
) -> dict:
    if not client_id:
        meta = _refusal_meta(
            route, "missing_client_id",
            "I don't have a client id for this session, so I can't look up your portfolio.",
        )
        return {"status": "missing_client_id", "meta": meta, "evidence": []}

    analysis = portfolio.analyze(client_id)
    if not analysis["holdings"]:
        meta = _refusal_meta(
            route, "empty_portfolio",
            "You don't have any holdings saved yet — add some in the Portfolio tab, then ask me again.",
        )
        return {"status": "empty_portfolio", "meta": meta, "evidence": []}

    port_chunk = build_portfolio_chunk(analysis)
    if question and _BENCHMARK_RE.search(question):
        line = _benchmark_line(client_id)
        if line:
            port_chunk["text"] += "\n" + line
    evidence = [port_chunk]
    for ticker in _top_movers(analysis, _TOP_MOVERS_FOR_NEWS):
        news_result = news_tool.news_headlines(ticker)
        evidence.extend(news_result.get("evidence", []))

    return {"status": "ok", "data": {"analysis": analysis}, "evidence": evidence}


def build_whatif_chunk(result: dict) -> dict:
    client_id = result["client_id"]
    as_of = result["as_of"]
    stamp = as_of.replace("+00:00", "Z").replace("-", "").replace(":", "")
    # Prefix must fit the citation regex's [A-Z]{2,4} cap (app.research.CITATION_RE) —
    # "WHATIF" (6 letters) silently fails to match, so citations would never be extracted.
    chunk_id = f"WIF-{client_id[:8]}-{stamp}"
    before, after = result["before"], result["after"]

    trade_desc = ", ".join(
        f"{'+' if t['delta_shares'] >= 0 else ''}{t['delta_shares']:.2f} shares of {t['ticker']}"
        for t in result["trades"]
    )
    lines = [f"Hypothetical trade: {trade_desc} (not executed — simulation only)."]
    lines.append(
        f"Before: total value {_fmt_money(before['total_value'])}"
        + (f", HHI {before['concentration']['hhi']} ({before['concentration']['band']})"
           if before["concentration"] else "") + "."
    )
    lines.append(
        f"After: total value {_fmt_money(after['total_value'])}"
        + (f", HHI {after['concentration']['hhi']} ({after['concentration']['band']})"
           if after["concentration"] else "") + "."
    )
    for h in after["holdings"]:
        lines.append(
            f"- {h['ticker']} ({h['company']}) after: {h['shares']:.4f} shares, "
            f"{_fmt_pct(h['weight'])} of portfolio."
        )

    text = (
        "[Portfolio What-If] Hypothetical simulation on the user's own saved holdings "
        "(nothing was bought or sold — this is a preview only)\n" + "\n".join(lines)
    )
    return {
        "chunk_id": chunk_id, "ticker": None, "company": "Your Portfolio (What-If)",
        "item": "Portfolio What-If", "section_title": "Hypothetical Trade",
        "filing_date": as_of, "fused_score": 1.0, "text": text, "kind": "portfolio_whatif",
        "as_of": as_of, "data": result,
    }


def portfolio_whatif_tool(
    client_id: str | None = None, question: str | None = None, route: dict | None = None, **_: Any
) -> dict:
    if not client_id:
        meta = _refusal_meta(
            route, "missing_client_id",
            "I don't have a client id for this session, so I can't simulate a trade.",
        )
        return {"status": "missing_client_id", "meta": meta, "evidence": []}

    if not portfolio.items(client_id):
        meta = _refusal_meta(
            route, "empty_portfolio",
            "You don't have any holdings saved yet — add some in the Portfolio tab, then ask me again.",
        )
        return {"status": "empty_portfolio", "meta": meta, "evidence": []}

    trades = portfolio.parse_whatif_trades(question or "", client_id)
    if not trades:
        meta = _refusal_meta(
            route, "unparseable_whatif",
            "I couldn't tell which trade you mean — try 'what if I bought 10 more shares of "
            "AAPL' or 'what if I trimmed my top holding by half'.",
        )
        return {"status": "unparseable_whatif", "meta": meta, "evidence": []}

    result = portfolio.whatif(client_id, trades)
    chunk = build_whatif_chunk(result)
    return {"status": "ok", "data": {"whatif": result}, "evidence": [chunk]}


def portfolio_filings(
    client_id: str | None = None, question: str | None = None, route: dict | None = None, **_: Any
) -> dict:
    """Holdings-aware Q&A: joins the user's own holdings with filing retrieval scoped to the
    tickers actually held AND ingested. Bounded to PORTFOLIO_FILINGS_MAX_TICKERS to keep the
    retrieval fan-out and context size in line with a single-company question.
    """
    if not client_id:
        meta = _refusal_meta(
            route, "missing_client_id",
            "I don't have a client id for this session, so I can't look up your portfolio.",
        )
        return {"status": "missing_client_id", "meta": meta, "evidence": []}

    analysis = portfolio.analyze(client_id)
    if not analysis["holdings"]:
        meta = _refusal_meta(
            route, "empty_portfolio",
            "You don't have any holdings saved yet — add some in the Portfolio tab, then ask me again.",
        )
        return {"status": "empty_portfolio", "meta": meta, "evidence": []}

    evidence = [build_portfolio_chunk(analysis)]
    active = set(universe.active_tickers())
    held_tickers = [h["ticker"] for h in analysis["holdings"]]
    covered = [t for t in held_tickers if t in active][: config.PORTFOLIO_FILINGS_MAX_TICKERS]
    if not covered:
        return {"status": "no_covered_holdings", "data": {"analysis": analysis}, "evidence": evidence}

    searched: list[str] = []
    for ticker in covered:
        # Prefix with the company name (same pattern as research._single_company_subs):
        # portfolio phrasing like "which of my holdings" doesn't resemble filing language on
        # its own, so a raw-question query under-scores against the dense similarity threshold.
        company = universe.company_name(ticker)
        query = question if company.lower() in (question or "").lower() else f"{company} {question or ''}".strip()
        res = retrieve.retrieve(query, [ticker], config.TOP_K_SUB)
        if res["top_sim"] >= config.DENSE_SIM_THRESHOLD:
            evidence.extend(res["chunks"])
            searched.append(ticker)

    return {"status": "ok", "data": {"analysis": analysis, "tickers_searched": searched}, "evidence": evidence}
