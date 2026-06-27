"""Hybrid tool router.

The deterministic route remains the default. A structured LLM router can be
enabled later for ambiguous mixed filing/market questions, but this module
always returns a bounded allowlisted plan.
"""

from __future__ import annotations

import re

from app import config, router
from app.tools.market import detect_market_intent


def _mentioned_tickers(question: str, route: dict) -> list[str]:
    tickers = list(route.get("tickers", []))
    low = question.lower()
    for alias, ticker in config.ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low) and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def route_tools(question: str, route: dict | None = None, metrics: list[str] | None = None) -> dict:
    """Return a deterministic, bounded tool plan for now."""
    route = route or router.route(question)
    metrics = metrics or []
    market = detect_market_intent(question)
    actions: list[dict] = []

    if route["mode"] == "clarify" and not market:
        actions.append({"tool": "refuse_or_clarify", "reason": "missing_company"})
    elif route["mode"] == "oos" and not market:
        actions.append({"tool": "filing_rag", "reason": "out_of_corpus_probe"})
    else:
        if metrics:
            actions.append({"tool": "facts_lookup", "metrics": metrics})
        if route["mode"] == "decompose":
            actions.append({"tool": "multi_company_compare", "tickers": route["tickers"]})
        elif not market or not metrics:
            actions.append({"tool": "filing_rag", "tickers": route["tickers"]})

        if market:
            for ticker in _mentioned_tickers(question, route):
                actions.append({"tool": "market_quote", "args": {"ticker": ticker}})

        actions.append({"tool": "synthesize_report"})

    return {
        "strategy": "bounded_hybrid_router",
        "route": route,
        "metrics": metrics,
        "market_intent": market,
        "actions": actions[: config.AGENT_MAX_STEPS],
    }
