"""Conversation context extraction for follow-up questions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app import router, universe


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

# A bare company swap ("What about AAPL?") names a new company but carries no intent words of
# its own — without this, it would fall into the "explicit company named" branch below as-is,
# losing whatever V3 intent (valuation/explain_move/...) the PRIOR question had, since intent
# detection re-runs regexes against this question's text alone.
_BARE_SWAP_RE = re.compile(r"^\s*(what|how)\s+about\b", re.I)


def _swap_company(prior_question: str, old_ticker: str, new_ticker: str) -> str:
    """Rewrite the prior question's company mention(s) to the new company, keeping its
    intent-triggering wording intact (e.g. "Is NVDA expensive?" + AAPL -> "Is Apple expensive?").
    """
    new_company = universe.company_name(new_ticker)
    old_company = universe.company_name(old_ticker)
    result = prior_question
    for old_name in sorted({old_company, old_ticker}, key=len, reverse=True):
        result = re.sub(rf"\b{re.escape(old_name)}\b", new_company, result, flags=re.I)
    return result


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
    1a. Question is a bare company swap ("What about AAPL?") naming a DIFFERENT company than
        the active one → rewrite the PRIOR question with the new company substituted in, so
        its intent wording (e.g. "expensive") carries over instead of being lost.
    1b. Question otherwise names a company explicitly → use as-stated; context is irrelevant.
    2. Plural pronoun (they/their/them/both) + multiple context tickers → prepend all
       recent companies so a cross-company follow-up stays multi-company.
    3. Singular pronoun (it/its/that/this) OR any topical financial keyword with no
       company → prepend the single active company (most recently named by the user).
    4. No signal → return unchanged; router handles clarify/oos paths normally.
    """
    if not context:
        return question, {}
    named = router.detect_companies(question)
    if named:
        new_ticker = named[-1]
        if (_BARE_SWAP_RE.match(question) and context.active_ticker
                and context.last_user_question and new_ticker != context.active_ticker):
            swapped = _swap_company(context.last_user_question, context.active_ticker, new_ticker)
            return swapped, context.as_dict()
        return question, context.as_dict()
    if not context.tickers:
        return question, context.as_dict()

    active = context.active_ticker

    # Plural pronoun with multiple prior companies → keep as multi-company
    if _PLURAL_PRONOUN_RE.search(question) and len(context.tickers) > 1:
        names = ", ".join(universe.company_name(t) for t in context.tickers)
        return f"For {names}, {question}", context.as_dict()

    # Singular pronoun or topical keyword → resolve to the one active company
    if active and (_SINGULAR_PRONOUN_RE.search(question) or _TOPICAL_FOLLOWUP_RE.search(question)):
        company = universe.company_name(active)
        return f"For {company}, {question}", context.as_dict()

    return question, context.as_dict()
