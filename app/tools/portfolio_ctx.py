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

from datetime import UTC, datetime
from typing import Any

from app import portfolio
from app.tools import news as news_tool

_TOP_MOVERS_FOR_NEWS = 2


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

    evidence = [build_portfolio_chunk(analysis)]
    for ticker in _top_movers(analysis, _TOP_MOVERS_FOR_NEWS):
        news_result = news_tool.news_headlines(ticker)
        evidence.extend(news_result.get("evidence", []))

    return {"status": "ok", "data": {"analysis": analysis}, "evidence": evidence}
