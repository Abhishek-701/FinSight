"""Hybrid tool router.

The deterministic route remains the default. A structured LLM router can be
enabled later for ambiguous mixed filing/market questions, but this module
always returns a bounded allowlisted plan.
"""

from __future__ import annotations

import re

from app import config, router
from app.tools.market import detect_market_intent


def _matches(pattern: str, question: str) -> bool:
    return bool(re.search(pattern, question, re.I))


def _mentioned_tickers(question: str, route: dict) -> list[str]:
    tickers = list(route.get("tickers", []))
    low = question.lower()
    for alias, ticker in config.ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low) and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _detect_screen_metric(question: str) -> str | None:
    for pattern, metric in config.SCREEN_METRIC_PATTERNS:
        if _matches(pattern, question):
            return metric
    return None


def route_tools(question: str, route: dict | None = None, metrics: list[str] | None = None) -> dict:
    """Return a deterministic, bounded tool plan for now."""
    route = route or router.route(question)
    metrics = metrics or []
    market = detect_market_intent(question)
    segment = _matches(config.SEGMENT_INTENT_RE, question)
    compute = _matches(config.COMPUTE_INTENT_RE, question)
    history = market and _matches(r"\b(history|chart|over the last|past|month|week|year)\b", question)
    screen_metric = _detect_screen_metric(question)
    screen = route["mode"] == "decompose" and screen_metric is not None and bool(router.SUPERLATIVE_RE.search(question))
    actions: list[dict] = []

    if route["mode"] == "clarify" and not market:
        actions.append({"tool": "refuse_or_clarify", "reason": "missing_company"})
    elif route["mode"] == "oos" and not market:
        actions.append({"tool": "filing_rag", "reason": "out_of_corpus_probe"})
    else:
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

    return {
        "strategy": "bounded_hybrid_router",
        "route": route,
        "metrics": metrics,
        "market_intent": market,
        "segment_intent": segment,
        "compute_intent": compute,
        "screen_intent": screen,
        "actions": actions[: config.AGENT_MAX_STEPS],
    }
