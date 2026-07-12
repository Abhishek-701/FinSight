"""Hybrid tool router.

The deterministic route stays the default and handles unambiguous questions for free (clarify,
oos, segment, screener superlatives, plain metric/market/compute questions — see the bottom of
route_tools). For ambiguous or mixed filing+market V3 questions (valuation, explain-the-move,
insight-brief paraphrases), a structured LLM call (app.agent.router_plan) produces a bounded tool
plan; if that call or its validation fails for any reason, a deterministic V3 fallback (regex-only,
same patterns as the LLM trigger) covers the common phrasings so the feature still works with
FINSIGHT_USE_LLM_ROUTER=0 or no ANTHROPIC_API_KEY reachable.
"""

from __future__ import annotations

import re

from app import config, router, universe
from app.tools.market import detect_market_intent


def _matches(pattern: str, question: str) -> bool:
    return bool(re.search(pattern, question, re.I))


def _mentioned_tickers(question: str, route: dict) -> list[str]:
    tickers = list(route.get("tickers", []))
    if route.get("mode") == "needs_ingest" and route.get("ticker"):
        tickers.append(route["ticker"])  # not in our corpus yet, but yfinance can quote it now
    low = question.lower()
    for alias, ticker in universe.aliases().items():
        if re.search(rf"\b{re.escape(alias)}\b", low) and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _detect_screen_metric(question: str) -> str | None:
    for pattern, metric in config.SCREEN_METRIC_PATTERNS:
        if _matches(pattern, question):
            return metric
    return None


def _history_period(question: str) -> str:
    if _matches(r"\b(6\s*months?|six\s+months?)\b", question):
        return "6mo"
    if _matches(r"\b(3\s*months?|three\s+months?|quarter)\b", question):
        return "3mo"
    if _matches(r"\b(year|12\s*months?|annual)\b", question):
        return "1y"
    return "1mo"  # covers week/month phrasing and the unmarked default


def _deterministic_v3_actions(question: str, route: dict) -> tuple[str, list[dict]] | None:
    """Regex-only fallback for the V3 intents — same trigger vocabulary as the LLM router,
    so this covers the common phrasings when the LLM router is off or fails validation.
    """
    explain_move = _matches(config.EXPLAIN_MOVE_INTENT_RE, question)
    insight = not explain_move and _matches(config.INSIGHT_INTENT_RE, question)
    valuation = not explain_move and not insight and _matches(config.VALUATION_INTENT_RE, question)
    news = (
        not explain_move and not insight and not valuation
        and _matches(config.NEWS_INTENT_RE, question)
    )

    tickers = _mentioned_tickers(question, route)
    ticker = tickers[0] if tickers else None

    if explain_move:
        if not ticker:
            return None
        company = universe.company_name(ticker)
        actions = [
            {"tool": "market_history", "args": {"ticker": ticker, "period": _history_period(question)}},
            {"tool": "market_quote", "args": {"ticker": ticker}},
            {"tool": "compute_metric", "args": {"metric": "price_change"}},
            {"tool": "news_headlines", "args": {"ticker": ticker}},
            {"tool": "filing_rag", "args": {
                "question": f"{company} risk factors demand competition segments outlook"}},
        ]
        return "explain_move", actions

    if news:
        if not ticker:
            return None
        return "news", [{"tool": "news_headlines", "args": {"ticker": ticker}}]

    if insight:
        if not ticker:
            return None
        company = universe.company_name(ticker)
        actions = [
            {"tool": "company_insight", "args": {"ticker": ticker}},
            {"tool": "filing_rag", "args": {
                "question": f"{company} business overview products strategy risks outlook"}},
        ]
        return "insight", actions

    if valuation:
        # Cross-company superlatives ("which company has the lowest P/S ratio") are handled by
        # the screener branch below in route_tools, not here — gate on a single named company.
        if not ticker or route["mode"] != "single":
            return None
        actions = [
            {"tool": "facts_lookup", "args": {"metrics": config.VALUATION_FACT_METRICS}},
            {"tool": "market_quote", "args": {"ticker": ticker}},
            {"tool": "compute_metric", "args": {"metric": "pe_ratio"}},
            {"tool": "compute_metric", "args": {"metric": "ps_ratio"}},
            {"tool": "screen_companies", "args": {"metric": "ps_ratio", "order": "asc"}},
        ]
        return "valuation", actions

    return None


def _try_llm_route(question: str, route: dict) -> dict | None:
    from app.agent import router_plan

    try:
        raw = router_plan.llm_route(question, route)
        return router_plan.validate_plan(raw, route)
    except Exception:  # noqa: BLE001 - any router failure falls back to deterministic routing
        return None


def route_tools(question: str, route: dict | None = None, metrics: list[str] | None = None) -> dict:
    """Return a bounded tool plan for the question."""
    route = route or router.route(question)
    metrics = metrics or []
    market = detect_market_intent(question)
    segment = _matches(config.SEGMENT_INTENT_RE, question)
    compute = _matches(config.COMPUTE_INTENT_RE, question)
    history = market and _matches(r"\b(history|chart|over the last|past|month|week|year)\b", question)
    screen_metric = _detect_screen_metric(question)
    screen = route["mode"] == "decompose" and screen_metric is not None and bool(router.SUPERLATIVE_RE.search(question))

    base = {
        "route": route, "metrics": metrics, "market_intent": market, "segment_intent": segment,
        "compute_intent": compute, "screen_intent": screen,
    }

    if _matches(config.PORTFOLIO_INTENT_RE, question):
        # Checked before clarify/oos: a portfolio question never names a company, so route()
        # would otherwise classify it as clarify/oos and this branch would never be reached.
        return {**base, "strategy": "deterministic", "intent": "portfolio",
                "actions": [{"tool": "portfolio_context"}, {"tool": "synthesize_report"}]}

    if route["mode"] == "clarify" and not market:
        return {**base, "strategy": "deterministic",
                "actions": [{"tool": "refuse_or_clarify", "reason": "missing_company"}]}
    if route["mode"] == "oos" and not market:
        return {**base, "strategy": "deterministic",
                "actions": [{"tool": "filing_rag", "reason": "out_of_corpus_probe"}]}
    if route["mode"] == "needs_ingest" and not market:
        # A real, not-yet-ingested ticker and no market intent -> the question needs the filing
        # corpus (facts/RAG), which we don't have for it yet. Offer to ingest instead of
        # refusing outright or running a wasted RAG probe (app.research._offer_ingest handles
        # this reason). If market intent IS present, fall through below: market_quote/history
        # work for any ticker without ingestion (registry.py's ticker arg_spec is unconstrained).
        return {**base, "strategy": "deterministic",
                "actions": [{"tool": "refuse_or_clarify", "reason": "needs_ingest"}]}

    # Segment and screener-superlative questions have unambiguous deterministic handling below
    # (the original generic branch) — never worth an LLM call, and screen already resolves the
    # "which company has the lowest P/S ratio" case that would otherwise look like valuation.
    if not segment and not screen:
        if config.USE_LLM_ROUTER and _matches(config.LLM_ROUTER_TRIGGER_RE, question):
            llm_plan = _try_llm_route(question, route)
            if llm_plan is not None:
                return {**base, "strategy": "llm_router", "intent": llm_plan["intent"],
                        "actions": llm_plan["actions"][: config.AGENT_MAX_STEPS]}

        v3 = _deterministic_v3_actions(question, route)
        if v3 is not None:
            intent, actions = v3
            actions = actions[: config.AGENT_MAX_STEPS - 1]
            actions.append({"tool": "synthesize_report"})
            return {**base, "strategy": "deterministic", "intent": intent, "actions": actions}

    # Original generic deterministic logic — plain filings/market/compute/screener questions.
    actions: list[dict] = []
    if metrics and not segment:
        actions.append({"tool": "facts_lookup", "metrics": metrics})
    if segment:
        actions.append({"tool": "filing_rag", "tickers": route["tickers"], "reason": "segment_intent"})
    elif route["mode"] == "decompose":
        actions.append({"tool": "multi_company_compare", "tickers": route["tickers"]})
    elif not market and not metrics:
        actions.append({"tool": "filing_rag", "tickers": route["tickers"]})

    if screen:
        order = "asc" if _matches(config.SCREEN_ORDER_ASC_RE, question) else "desc"
        actions.append({"tool": "screen_companies", "args": {"metric": screen_metric, "order": order}})

    if market and not screen:
        for ticker in _mentioned_tickers(question, route):
            actions.append({"tool": "market_history" if history else "market_quote",
                            "args": {"ticker": ticker}})

    if compute and not screen:
        actions.append({"tool": "compute_metric", "args": {"metric": "market_cap_to_revenue"}})

    actions.append({"tool": "synthesize_report"})

    return {**base, "strategy": "bounded_hybrid_router", "actions": actions[: config.AGENT_MAX_STEPS]}
