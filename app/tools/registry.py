"""Allowlisted tool registry for bounded agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., dict[str, Any]]
    # arg_name -> allowed enum values (list) for scalar args, a zero-arg callable returning
    # such a list (resolved at validation time so it tracks the live universe — see
    # app.universe.active_tickers), or the sentinel "*" for unconstrained args (question/reason
    # free text, inputs dict). Used to validate LLM-planned actions (app/agent/router_plan.py);
    # the deterministic router doesn't need it since its args are hand-written, but tools are
    # validated uniformly.
    arg_spec: dict[str, Any] = field(default_factory=dict)


class ToolResult(dict):
    """Dictionary result with a consistent status envelope."""


def _company_insight(**kwargs: Any) -> dict[str, Any]:
    # Lazy, like filings.py's `from app import research` inside each function: app.insight
    # imports app.research (for its citation/SSE helpers), which imports this registry via
    # the executor — importing app.insight at _load_specs() module-load time would cycle back
    # here before app.insight finishes defining company_insight.
    from app import insight

    return insight.company_insight(**kwargs)


def _load_specs() -> dict[str, ToolSpec]:
    from app import config, universe
    from app.screener import DERIVED_METRICS
    from app.tools import compute, filings, market, news, portfolio_ctx, screen

    tickers = universe.active_tickers  # callable: re-resolved at validation time, not import time
    xbrl_metrics = sorted({metric for _, metric in config.XBRL_KEYWORD_MAP})
    compute_metrics = list(compute._METRIC_HANDLERS)  # noqa: SLF001 - registry owns tool internals

    specs = [
        ToolSpec("refuse_or_clarify", "Return a clarification refusal.", filings.refuse_or_clarify),
        ToolSpec(
            "facts_lookup",
            "Look up structured XBRL filing facts (revenue, net income, EPS, etc.) for a company.",
            filings.facts_lookup,
            arg_spec={"metrics": xbrl_metrics},
        ),
        ToolSpec(
            "filing_rag",
            "Run grounded retrieval + synthesis over filing text chunks for one company.",
            filings.filing_rag,
            arg_spec={"tickers": tickers, "question": "*", "reason": "*"},
        ),
        ToolSpec(
            "multi_company_compare",
            "Run filing retrieval across multiple companies for comparison questions.",
            filings.filing_rag,
            arg_spec={"tickers": tickers},
        ),
        ToolSpec(
            "market_quote",
            "Fetch latest live/delayed quote data (price, market cap, change) for one ticker.",
            # Unconstrained: yfinance serves any US ticker regardless of our filing corpus,
            # and the handler already fails gracefully (status: error) on a bad symbol — no
            # need to gate this on the ingested-company enum like the filing-grounded tools.
            market.market_quote,
            arg_spec={"ticker": "*"},
        ),
        ToolSpec(
            "market_history",
            "Fetch recent OHLCV price history for one ticker over a period.",
            market.market_history,
            arg_spec={"ticker": "*", "period": list(config.MARKET_HISTORY_PERIODS)},
        ),
        ToolSpec(
            "news_headlines",
            "Fetch recent third-party news headlines for one ticker — reported context, "
            "never a verified cause of a price move. Unconstrained like market tools: "
            "works for any ticker regardless of filing coverage.",
            news.news_headlines,
            arg_spec={"ticker": "*"},
        ),
        ToolSpec(
            "compute_metric",
            "Compute a small deterministic ratio (pe_ratio, ps_ratio, price_change, "
            "market_cap_to_revenue) from evidence already gathered this turn.",
            compute.compute_metric,
            arg_spec={"metric": compute_metrics, "inputs": "*"},
        ),
        ToolSpec(
            "screen_companies",
            "Rank all six covered companies by a derived financial metric "
            "(operating_margin, net_margin, revenue_growth_yoy, roe, ps_ratio).",
            screen.screen_companies,
            arg_spec={"metric": list(DERIVED_METRICS), "order": ["asc", "desc"]},
        ),
        ToolSpec(
            "company_insight",
            "Assemble a one-company insight brief: live quote, price trend, valuation "
            "ratios, screener ranks, and filing evidence for one ticker.",
            _company_insight,
            arg_spec={"ticker": tickers},
        ),
        ToolSpec(
            "portfolio_context",
            "Assemble the requesting user's own portfolio: holdings, live valuation, P&L, "
            "concentration, and news for the biggest movers. Takes no arguments — the plan "
            "only decides WHETHER to call it; WHOSE portfolio it reads is injected by the "
            "executor from the authenticated request, never chosen by a plan.",
            portfolio_ctx.portfolio_context,
            arg_spec={},
        ),
    ]
    return {spec.name: spec for spec in specs}


TOOL_REGISTRY: dict[str, ToolSpec] = _load_specs()


def validate_args(tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """Drop unknown keys; return None if any known key holds a value outside its enum.

    "*" in arg_spec means unconstrained (free text / dict) — any value is accepted.
    An arg_spec entry may also be a zero-arg callable (e.g. universe.active_tickers) resolved
    here, at validation time, so the allowed set tracks the live universe.
    A list arg (e.g. tickers) is validated element-wise against the same enum.
    """
    spec = TOOL_REGISTRY.get(tool)
    if spec is None:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in args.items():
        if key not in spec.arg_spec:
            continue
        allowed = spec.arg_spec[key]
        if allowed == "*":
            cleaned[key] = value
            continue
        if callable(allowed):
            allowed = allowed()
        values = value if isinstance(value, list) else [value]
        if not all(v in allowed for v in values):
            return None
        cleaned[key] = value
    return cleaned


def run_tool(name: str, **kwargs: Any) -> ToolResult:
    if name not in TOOL_REGISTRY:
        return ToolResult({"tool": name, "status": "error", "error": "tool_not_allowed"})
    try:
        result = TOOL_REGISTRY[name].handler(**kwargs)
    except Exception as exc:  # noqa: BLE001 - tool boundary must return structured errors
        return ToolResult({"tool": name, "status": "error", "error": str(exc)})
    return ToolResult({"tool": name, **result})
