"""Company Insight Brief — fuses live market data with XBRL fundamentals and filing RAG.

build_brief_data() assembles the deterministic card (quote, price trend, valuation ratios,
screener ranks) — used both as the company_insight chat tool and as the data half of the
/api/insight endpoints. brief()/stream_brief() add two focused narrative sections on top
(the _run_summary per-topic pattern from research.py, scoped to one ticker) plus a
code-assembled valuation paragraph — no LLM call for the numbers, only for the prose.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from app import config, facts, retrieve, screener, synthesize, universe
from app.research import CITATION_RE, _citation_payload, _elapsed, sse
from app.tools import compute, market, news as news_tool

_NARRATIVE_TOPICS: list[tuple[str, str]] = [
    ("business overview main products strategy growth outlook", "Business & Outlook"),
    ("key risk factors business operational and regulatory risks", "Key Risks"),
]


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
    company = universe.company_name(ticker)
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

    news_result = news_tool.news_headlines(ticker)
    news_items = news_result.get("data", {}).get("items", [])
    evidence.extend(news_result.get("evidence", []))

    return {
        "ticker": ticker,
        "company": company,
        "as_of": _now_iso(),
        "quote": quote_data,
        "history": history_data,
        "fundamentals": fundamentals,
        "valuation": valuation,
        "ranks": ranks,
        "news": news_items,
        "disclaimer": config.MARKET_DISCLAIMER,
        "evidence": evidence,
        "market_status": market_status,
    }


def company_insight(ticker: str | None = None, question: str | None = None,
                    route: dict | None = None, **_: object) -> dict:
    """Chat tool: assemble the insight card and return it as citable evidence."""
    ticker = ticker or ((route or {}).get("tickers") or [None])[0]
    if not ticker or not universe.is_ingested(ticker.upper()):
        return {"status": "missing_ticker", "data": {}, "evidence": []}
    data = build_brief_data(ticker)
    return {
        "status": "ok",
        "data": {"valuation": data["valuation"], "ranks": data["ranks"],
                 "market_status": data["market_status"]},
        "evidence": data["evidence"],
    }


_CARD_KEYS = ("ticker", "company", "as_of", "quote", "history", "fundamentals",
             "valuation", "ranks", "news", "disclaimer", "market_status")


def _valuation_paragraph(data: dict) -> str:
    """Code-assembled valuation paragraph (no LLM) with inline [chunk_id] citations."""
    valuation = data["valuation"]
    if not valuation:
        return ""
    calc_chunks = {c["data"]["metric"]: c for c in data["evidence"] if c.get("kind") == "compute"}

    def _cite(metric: str) -> str:
        chunk = calc_chunks.get(metric)
        return f" [{chunk['chunk_id']}]" if chunk else ""

    parts: list[str] = []
    pe = valuation.get("pe_ratio")
    if pe:
        parts.append(f"P/E ratio is **{pe['value']:.2f}x** ({pe['formula']}){_cite('pe_ratio')}.")
    ps = valuation.get("ps_ratio")
    if ps:
        parts.append(f"P/S ratio is **{ps['value']:.2f}x** ({ps['formula']}){_cite('ps_ratio')}.")
    change = valuation.get("price_change")
    if change:
        direction = "up" if change["value"] >= 0 else "down"
        parts.append(
            f"Price is {direction} **{abs(change['value']):.2f}%** over the "
            f"{config.INSIGHT_HISTORY_PERIOD} window{_cite('price_change')}."
        )
    if not parts:
        return ""
    return "### Valuation Snapshot\n" + " ".join(parts) + f" {config.MARKET_DISCLAIMER}"


def brief(ticker: str) -> dict:
    """Non-streaming insight brief: deterministic card + 2 focused narrative sections."""
    started = time.perf_counter()
    data = build_brief_data(ticker)
    ticker, company = data["ticker"], data["company"]

    sections: list[str] = []
    all_cited: set[str] = set()
    retrieval_log: list[dict] = []
    tool_calls: list[dict] = [{"tool": "company_insight", "status": data["market_status"]}]
    rag_chunks: dict[str, dict] = {}

    valuation_paragraph = _valuation_paragraph(data)
    if valuation_paragraph:
        sections.append(valuation_paragraph)
        all_cited.update(CITATION_RE.findall(valuation_paragraph))

    for suffix, title in _NARRATIVE_TOPICS:
        query = f"{company} {suffix}"
        res = retrieve.retrieve(query, [ticker], config.TOP_K_SUB)
        retrieval_log.append({"ticker": ticker, "query": query, "top_sim": round(res["top_sim"], 3),
                              "chunk_ids": [c["chunk_id"] for c in res["chunks"]]})
        if res["top_sim"] < config.DENSE_SIM_THRESHOLD:
            continue
        for c in res["chunks"]:
            rag_chunks[c["chunk_id"]] = c
        synth_t0 = time.perf_counter()
        paragraph = synthesize.synthesize_section(query, res["chunks"])
        elapsed = _elapsed(synth_t0)
        if paragraph.strip():
            cited_here = set(CITATION_RE.findall(paragraph))
            all_cited.update(cited_here)
            sections.append(f"### {title}\n{paragraph}")
            tool_calls.append({"tool": "synthesize_section", "topic": title, "status": "ok",
                               "citations": sorted(cited_here), "elapsed_ms": elapsed})

    answer = f"## {company} — Insight Brief\n\n" + (
        "\n\n".join(sections) if sections else "No brief could be generated for this company."
    )
    context_chunks = list({**{c["chunk_id"]: c for c in data["evidence"]}, **rag_chunks}.values())
    cited = sorted(all_cited)

    return {
        **{k: data[k] for k in _CARD_KEYS},
        "answer": answer,
        "citations": cited,
        "citation_details": _citation_payload(cited, context_chunks),
        "retrieval": retrieval_log,
        "tool_calls": tool_calls,
        "elapsed_ms": _elapsed(started),
    }


def stream_brief(ticker: str):
    """SSE generator: `card` event immediately, then narrative `token` events, then `done`."""
    started = time.perf_counter()
    data = build_brief_data(ticker)
    ticker, company = data["ticker"], data["company"]

    yield sse("card", {k: data[k] for k in _CARD_KEYS})

    header = f"## {company} — Insight Brief\n\n"
    yield sse("token", {"text": header})

    all_cited: set[str] = set()
    tool_calls: list[dict] = [{"tool": "company_insight", "status": data["market_status"]}]
    rag_chunks: dict[str, dict] = {}

    valuation_paragraph = _valuation_paragraph(data)
    if valuation_paragraph:
        block = valuation_paragraph + "\n\n"
        yield sse("token", {"text": block})
        all_cited.update(CITATION_RE.findall(valuation_paragraph))

    for suffix, title in _NARRATIVE_TOPICS:
        query = f"{company} {suffix}"
        res = retrieve.retrieve(query, [ticker], config.TOP_K_SUB)
        if res["top_sim"] < config.DENSE_SIM_THRESHOLD:
            continue
        for c in res["chunks"]:
            rag_chunks[c["chunk_id"]] = c

        yield sse("token", {"text": f"### {title}\n"})

        synth_t0 = time.perf_counter()
        para_acc: list[str] = []
        for token in synthesize.stream_section(query, res["chunks"]):
            para_acc.append(token)
            yield sse("token", {"text": token})

        cited_here = set(CITATION_RE.findall("".join(para_acc)))
        all_cited.update(cited_here)
        tool_calls.append({"tool": "synthesize_section", "topic": title, "status": "ok",
                           "citations": sorted(cited_here), "elapsed_ms": _elapsed(synth_t0)})
        yield sse("token", {"text": "\n\n"})

    cited = sorted(all_cited)
    context_chunks = list({**{c["chunk_id"]: c for c in data["evidence"]}, **rag_chunks}.values())
    yield sse("done", {
        "citations": _citation_payload(cited, context_chunks),
        "tool_calls": tool_calls,
        "market_status": data["market_status"],
        "elapsed_ms": _elapsed(started),
    })
