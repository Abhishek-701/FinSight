"""Conversation context extraction for follow-up questions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app import config, router


@dataclass
class ConversationContext:
    tickers: list[str]
    active_ticker: str | None  # most recent company named in a user message
    last_user_question: str | None
    last_assistant_summary: str | None

    def as_dict(self) -> dict:
        return {
            "tickers": self.tickers,
            "active_ticker": self.active_ticker,
            "last_user_question": self.last_user_question,
            "last_assistant_summary": self.last_assistant_summary,
        }


# Matches questions that are clearly about a business/financial topic but name no
# company — a strong signal the question continues the prior company's thread.
_TOPICAL_FOLLOWUP_RE = re.compile(
    r"\b(risk|revenue|income|profit|strategy|overview|segment|product|service|"
    r"performance|outlook|guidance|debt|equity|margin|eps|dividend|capex|r.?d|"
    r"employees?|competition|market\s+share|tell\s+me|what\s+about|how\s+about|"
    r"more\s+about|describe|summarize?|summary|business|financial|operation|"
    r"balance\s+sheet|cash\s+flow|earnings|growth|forecast|valuation)\b",
    re.I,
)

_PLURAL_PRONOUN_RE = re.compile(r"\b(they|their|them|both)\b", re.I)
_SINGULAR_PRONOUN_RE = re.compile(r"\b(it|its|that|this|same\s+company)\b", re.I)


def from_history(history: list[dict]) -> ConversationContext:
    tickers: list[str] = []
    last_user_question = None
    last_assistant_summary = None
    active_ticker: str | None = None

    for msg in history:
        content = msg.get("content", "")
        found = router.detect_companies(content)
        for ticker in found:
            if ticker not in tickers:
                tickers.append(ticker)
        if msg.get("role") == "user":
            last_user_question = content
            if found:
                active_ticker = found[-1]  # track most-recently-named company per user turn
        elif msg.get("role") == "assistant":
            last_assistant_summary = content[:500]

    return ConversationContext(
        tickers=tickers[-3:],
        active_ticker=active_ticker,
        last_user_question=last_user_question,
        last_assistant_summary=last_assistant_summary,
    )


def contextualize_question(question: str, context: ConversationContext | None) -> tuple[str, dict]:
    """Resolve follow-up questions by carrying forward the active company from history.

    Resolution priority (first match wins):
    1. Question names a company explicitly → use as-stated; context is irrelevant.
    2. Plural pronoun (they/their/them/both) + multiple context tickers → prepend all
       recent companies so a cross-company follow-up stays multi-company.
    3. Singular pronoun (it/its/that/this) OR any topical financial keyword with no
       company → prepend the single active company (most recently named by the user).
    4. No signal → return unchanged; router handles clarify/oos paths normally.
    """
    if not context:
        return question, {}
    if router.detect_companies(question):
        return question, context.as_dict()
    if not context.tickers:
        return question, context.as_dict()

    active = context.active_ticker

    # Plural pronoun with multiple prior companies → keep as multi-company
    if _PLURAL_PRONOUN_RE.search(question) and len(context.tickers) > 1:
        names = ", ".join(config.COMPANIES[t] for t in context.tickers)
        return f"For {names}, {question}", context.as_dict()

    # Singular pronoun or topical keyword → resolve to the one active company
    if active and (_SINGULAR_PRONOUN_RE.search(question) or _TOPICAL_FOLLOWUP_RE.search(question)):
        company = config.COMPANIES[active]
        return f"For {company}, {question}", context.as_dict()

    return question, context.as_dict()
