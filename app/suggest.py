"""Deterministic proactive follow-up suggestions shown as chips after an answer.

Templates only, no LLM call — keyed off the plan's intent (app.agent.router_llm/router_plan)
and the primary ticker in play. Purely additive UI sugar; never affects the answer itself.
"""

from __future__ import annotations

from app import universe

_TEMPLATES: dict[str, list[str]] = {
    "valuation": [
        "Why did {company} move this month?",
        "How does {company} rank on operating margin?",
    ],
    "explain_move": [
        "Is {company} expensive right now?",
        "What risk factors did {company} disclose?",
    ],
    "insight": [
        "Is {company} expensive right now?",
        "Why did {company} move this month?",
    ],
    "news": [
        "Is {company} expensive right now?",
    ],
    "comparison": [
        "Why did {company} move this month?",
        "How does {company} rank on operating margin?",
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
    "What risk factors did {company} disclose?",
    "What is {company}'s latest reported revenue?",
]


def suggest(
    intent: str | None, ticker: str | None, refused: bool, refusal_reason: str | None,
) -> list[str]:
    """Return up to 3 follow-up question templates, or [] when nothing sensible applies."""
    if refusal_reason == "needs_ingest" and ticker:
        company = universe.company_name(ticker)
        return [
            f"Once added, is {company} expensive right now?",
            f"Once added, what is {company}'s latest reported revenue?",
        ]
    if refused:
        return []
    if intent in _NO_TICKER_INTENTS:
        return list(_TEMPLATES[intent])
    if not ticker:
        return []
    company = universe.company_name(ticker)
    templates = _TEMPLATES.get(intent or "", _GENERIC)
    return [t.format(company=company) for t in templates][:3]
