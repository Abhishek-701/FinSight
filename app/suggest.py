"""Deterministic proactive follow-up suggestions shown as chips after an answer.

Templates only, no LLM call — keyed off the plan's intent (app.agent.router_llm/router_plan)
and the primary ticker in play. Purely additive UI sugar; never affects the answer itself.
"""

from __future__ import annotations

from app import universe

_TEMPLATES: dict[str, list[str]] = {
    "valuation": [
        "How does {company} rank on operating margin?",
        "What is {company}'s latest reported revenue?",
    ],
    "explain_move": [
        "What risk factors did {company} disclose?",
        "What is {company}'s latest reported revenue?",
    ],
    "insight": [
        "What risk factors did {company} disclose?",
        "How does {company} rank on operating margin?",
    ],
    "news": [
        "What is {company}'s latest reported revenue?",
        "What risk factors did {company} disclose?",
    ],
    "comparison": [
        "How does {company} rank on operating margin?",
        "What is {company}'s latest reported revenue?",
    ],
    "portfolio": [
        "How concentrated is my portfolio?",
        "Which of my holdings is most exposed to risk?",
    ],
    "portfolio_whatif": [
        "How concentrated would my portfolio be after that?",
        "What if I did the opposite trade instead?",
    ],
    "portfolio_filings": [
        "How is my portfolio doing overall?",
        "How concentrated is my portfolio?",
    ],
}

_NO_TICKER_INTENTS = ("portfolio", "portfolio_whatif", "portfolio_filings")

_GENERIC = [
    "How does {company} rank on operating margin?",
    "What is {company}'s latest reported revenue?",
]


def _fresh(questions: list[str], asked: list[str] | None) -> list[str]:
    seen = {a.strip().lower() for a in (asked or []) if a}
    return [q for q in questions if q.strip().lower() not in seen][:3]


def suggest(
    intent: str | None, ticker: str | None, refused: bool, refusal_reason: str | None,
    asked: list[str] | None = None,
) -> list[str]:
    """Return up to 3 follow-up question templates, or [] when nothing sensible applies."""
    if refusal_reason == "needs_ingest" and ticker:
        company = universe.company_name(ticker)
        return _fresh([
            f"Once added, is {company} expensive right now?",
            f"Once added, what is {company}'s latest reported revenue?",
        ], asked)
    if refused:
        return []
    if intent in _NO_TICKER_INTENTS:
        return _fresh(list(_TEMPLATES[intent]), asked)
    if not ticker:
        return []
    company = universe.company_name(ticker)
    templates = _TEMPLATES.get(intent or "", _GENERIC)
    return _fresh([t.format(company=company) for t in templates], asked)
