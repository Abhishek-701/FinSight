"""Hybrid LLM tool router — the "structured LLM router" reserved by router_llm.py's docstring.

Deterministic regex routing stays the default and handles unambiguous questions for free.
For ambiguous or mixed filing+market questions (V3: valuation, explain-the-move, insight-brief
paraphrases that don't match the fallback regexes), one temp-0 structured-JSON call to a cheap
model (claude-haiku-4-5) produces a bounded tool plan. The plan is never trusted directly:
validate_plan() allowlists tools via the registry, validates args against each tool's arg_spec,
fixes evidence-before-compute ordering, and caps step count. Any failure — bad JSON, unknown
tool, invalid arg, empty plan, API error — returns None and the caller falls back to the
deterministic branches in router_llm.py.
"""

from __future__ import annotations

import json

import anthropic

from app import config, universe
from app.tools.registry import TOOL_REGISTRY, validate_args

try:
    from cachetools import TTLCache
except ImportError:  # pragma: no cover
    TTLCache = None

_client = anthropic.Anthropic()

_INTENTS = ["valuation", "explain_move", "insight", "news", "hybrid", "filings_only", "market_only"]

# Tools the LLM router may plan. refuse_or_clarify is deterministic-only (router.py already
# decides clarify/oos before the LLM router ever fires).
_PLANNABLE_TOOLS = [
    "facts_lookup", "filing_rag", "multi_company_compare", "market_quote", "market_history",
    "news_headlines", "compute_metric", "screen_companies", "company_insight",
]

_PLAN_CACHE = TTLCache(maxsize=256, ttl=config.ROUTER_CACHE_TTL_SECONDS) if TTLCache else {}


def _build_schema() -> dict:
    from app.screener import DERIVED_METRICS
    from app.tools import compute

    tickers = universe.active_tickers()
    xbrl_metrics = sorted({metric for _, metric in config.XBRL_KEYWORD_MAP})
    compute_metrics = list(compute._METRIC_HANDLERS)  # noqa: SLF001
    def _nullable_enum(values: list[str]) -> dict:
        return {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}]}

    action_schema = {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": _PLANNABLE_TOOLS},
            "ticker": _nullable_enum(tickers),
            "metric": _nullable_enum([*compute_metrics, *DERIVED_METRICS]),
            "metrics": {"anyOf": [
                {"type": "array", "items": {"type": "string", "enum": xbrl_metrics}},
                {"type": "null"},
            ]},
            "period": _nullable_enum(list(config.MARKET_HISTORY_PERIODS)),
            "order": _nullable_enum(["asc", "desc"]),
            "question": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["tool", "ticker", "metric", "metrics", "period", "order", "question"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": _INTENTS},
            "actions": {"type": "array", "items": action_schema},
        },
        "required": ["intent", "actions"],
        "additionalProperties": False,
    }


_SYSTEM = (
    "You plan which tools to call to answer a financial question about six companies: "
    "Apple (AAPL), JPMorgan Chase (JPM), Walmart (WMT), Coca-Cola (KO), NVIDIA (NVDA), "
    "Caterpillar (CAT).\n\n"
    "Available tools:\n"
    "- facts_lookup(metrics): structured XBRL numbers (revenue, net_income, eps_diluted, etc.) "
    "for ONE company. Use for any question needing a historical filed figure.\n"
    "- filing_rag(question) / multi_company_compare: retrieval + synthesis over filing text "
    "(risks, strategy, segments, MD&A). Use when the question needs prose/context from the "
    "filing, not just a number.\n"
    "- market_quote(ticker): live/delayed price, market cap, change.\n"
    "- market_history(ticker, period): OHLCV price history over 1mo/3mo/6mo/1y.\n"
    "- news_headlines(ticker): recent third-party news headlines. Reported context only — "
    "never a verified cause of a price move. Use for explain_move (place it alongside market "
    "evidence, before filing_rag) and for plain 'what's the news on X' questions.\n"
    "- compute_metric(metric): pe_ratio, ps_ratio, price_change, or market_cap_to_revenue — "
    "computed from evidence gathered by EARLIER actions in your plan, so always place a "
    "facts_lookup/market_quote/market_history action before the compute_metric action(s) that "
    "need their evidence.\n"
    "- screen_companies(metric, order): ranks all six companies by a derived metric "
    "(operating_margin, net_margin, revenue_growth_yoy, roe, ps_ratio). Use for cross-company "
    "'which company has the highest/lowest X' questions — NOT for single-company valuation.\n"
    "- company_insight(ticker): one-call bundle of quote + valuation + screener ranks for one "
    "company. Use for 'give me a brief/overview/snapshot on <company>' requests, paired with a "
    "filing_rag call for narrative context.\n\n"
    "Pick intent: valuation (is X expensive/cheap, P/E, P/S), explain_move (why did the stock "
    "move), insight (full brief/snapshot on one company), news (plain 'what's the news on X'), "
    "hybrid (mixes filing + market data some other way), filings_only, or market_only.\n\n"
    "Keep plans short (2-5 actions) and put evidence-gathering actions before any compute_metric "
    "that depends on them. Do not invent tools or values outside the enums.\n\n"
    "Examples:\n"
    "Q: 'Is NVIDIA expensive right now?' -> intent=valuation, actions=["
    "facts_lookup(metrics=[revenue,net_income,eps_diluted], ticker=NVDA), "
    "market_quote(ticker=NVDA), compute_metric(metric=pe_ratio), "
    "compute_metric(metric=ps_ratio), screen_companies(metric=ps_ratio, order=asc)]\n"
    "Q: 'Why is NVIDIA down this month?' -> intent=explain_move, actions=["
    "market_history(ticker=NVDA, period=1mo), market_quote(ticker=NVDA), "
    "compute_metric(metric=price_change), news_headlines(ticker=NVDA), "
    "filing_rag(question='NVIDIA risk factors demand competition segments outlook')]\n"
    "Q: 'What's the latest news on Apple?' -> intent=news, actions=["
    "news_headlines(ticker=AAPL)]\n"
    "Q: 'Give me an insight brief on Apple' -> intent=insight, actions=["
    "company_insight(ticker=AAPL), "
    "filing_rag(question='Apple business overview products strategy risks outlook')]\n"
    "Q: 'Which company has the lowest P/S ratio?' -> intent=market_only, "
    "actions=[screen_companies(metric=ps_ratio, order=asc)] "
    "(NOT valuation — this is a cross-company screener question, no single ticker).\n"
    "Q: 'What was Apple's revenue last year?' -> intent=filings_only, "
    "actions=[facts_lookup(metrics=[revenue], ticker=AAPL)]"
)


def _cache_key(question: str, route: dict) -> tuple:
    return (question.strip().lower(), tuple(sorted(route.get("tickers", []))))


def llm_route(question: str, route: dict) -> dict | None:
    """One structured-output call to ROUTER_MODEL. Returns the parsed {intent, actions} dict,
    or None on any API/parse failure (caller falls back to the deterministic router).
    """
    key = _cache_key(question, route)
    if key in _PLAN_CACHE:
        return _PLAN_CACHE[key]
    try:
        msg = _client.messages.create(
            model=config.ROUTER_MODEL,
            max_tokens=config.ROUTER_MAX_TOKENS,
            temperature=config.TEMPERATURE,
            system=_SYSTEM,
            messages=[{"role": "user", "content": f"Question: {question}"}],
            output_config={"format": {"type": "json_schema", "schema": _build_schema()}},
        )
        text = next(b.text for b in msg.content if b.type == "text")
        raw = json.loads(text)
    except Exception:  # noqa: BLE001 - any router failure falls back to deterministic routing
        return None
    _PLAN_CACHE[key] = raw
    return raw


def _args_for(tool: str, action: dict) -> dict | None:
    """Map one raw LLM action into a tool's args dict. Returns None if a required field is missing."""
    if tool == "facts_lookup":
        return {"metrics": action["metrics"]} if action.get("metrics") else {}
    if tool in ("filing_rag", "multi_company_compare"):
        return {"question": action["question"]} if action.get("question") else {}
    if tool in ("market_quote", "company_insight", "news_headlines"):
        return {"ticker": action["ticker"]} if action.get("ticker") else None
    if tool == "market_history":
        if not action.get("ticker"):
            return None
        args = {"ticker": action["ticker"]}
        if action.get("period"):
            args["period"] = action["period"]
        return args
    if tool == "compute_metric":
        return {"metric": action["metric"]} if action.get("metric") else None
    if tool == "screen_companies":
        if not action.get("metric"):
            return None
        return {"metric": action["metric"], "order": action.get("order") or "desc"}
    return None


def validate_plan(raw: dict | None, route: dict) -> dict | None:
    """Validate + repair a raw LLM plan into {"intent", "actions"}. Returns None if unfixable."""
    if not raw or raw.get("intent") not in _INTENTS:
        return None
    raw_actions = raw.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        return None

    evidence_actions: list[dict] = []
    compute_actions: list[dict] = []
    for raw_action in raw_actions:
        if not isinstance(raw_action, dict):
            return None
        tool = raw_action.get("tool")
        if tool not in TOOL_REGISTRY or tool not in _PLANNABLE_TOOLS:
            return None
        args = _args_for(tool, raw_action)
        if args is None:
            return None
        cleaned = validate_args(tool, args)
        if cleaned is None:
            return None
        action = {"tool": tool, "args": cleaned}
        if tool == "compute_metric":
            compute_actions.append(action)
        else:
            evidence_actions.append(action)

    if compute_actions and not evidence_actions:
        return None  # compute_metric has nothing to compute from

    actions = evidence_actions + compute_actions
    actions = actions[: config.AGENT_MAX_STEPS - 1]
    actions.append({"tool": "synthesize_report"})
    return {"intent": raw["intent"], "actions": actions}
