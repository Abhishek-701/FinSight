"""Phase 3 — regex/alias router (no LLM, for explainability + determinism; see DECISIONS.md).

Decides how a question is handled:
  - >=1 of our six companies named   -> "single" (1) or "decompose" (2+), filtered retrieval
  - 0 named + superlative wording     -> "decompose" over all six
  - 0 named + a specific OTHER entity -> "oos" (out-of-corpus): retrieve unfiltered, let the
                                          dense-similarity threshold gate decide (e.g. "Tesla's revenue")
  - 0 named + nothing specific        -> "clarify": ask for the company, do not guess
"""

import re

from app import universe

SUPERLATIVE_RE = re.compile(
    # "most(?!\s+recent...)" so "most recent fiscal year" is NOT read as a superlative — that
    # phrasing was misrouting out-of-corpus questions (e.g. "Amazon's ... most recent year") to
    # decomposition instead of the oos/threshold gate.
    r"\b(highest|lowest|most(?!\s+recent)|least|largest|smallest|greatest|biggest|top|best|worst|"
    r"more than|less than|compare|compared|versus|vs\.?|which (?:company|of)|rank|ranked)\b",
    re.I,
)
# A capitalized token (optionally possessive) that may name a company. Used only when none of
# our six matched, to tell "Tesla's revenue" (a real but out-of-corpus entity) from "what was
# revenue?" (no entity at all). STOPWORDS strips sentence-initial / interrogative capitals.
NAMED_ENTITY_RE = re.compile(r"\b([A-Z][A-Za-z][A-Za-z.&-]+)(?:'s)?\b")
STOPWORDS = {"what", "which", "who", "how", "when", "where", "why", "the", "a", "an", "is",
             "was", "were", "did", "do", "does", "of", "in", "for", "and", "or", "their",
             "its", "these", "those", "report", "reported", "revenue", "company", "companies"}


def detect_companies(question: str) -> list[str]:
    """Return tickers for any active company named via the alias map (whole-word, case-insensitive)."""
    found = []
    low = question.lower()
    for alias, ticker in universe.aliases().items():
        if re.search(rf"\b{re.escape(alias)}\b", low) and ticker not in found:
            found.append(ticker)
    return found


def has_other_named_entity(question: str) -> bool:
    """True if the question names a specific proper-noun entity that is NOT an active company."""
    aliases = universe.aliases()
    for m in NAMED_ENTITY_RE.finditer(question):
        token = m.group(1)
        if token.lower() in STOPWORDS:
            continue
        if token.lower() in aliases:
            continue  # one of ours — handled by detect_companies
        return True
    return False


def route(question: str) -> dict:
    tickers = detect_companies(question)
    if tickers:
        mode = "single" if len(tickers) == 1 else "decompose"
        return {"mode": mode, "tickers": tickers}
    if SUPERLATIVE_RE.search(question):
        return {"mode": "decompose", "tickers": universe.active_tickers()}  # compare across all active
    if has_other_named_entity(question):
        return {"mode": "oos", "tickers": []}  # specific but out-of-corpus -> threshold gate
    return {"mode": "clarify", "tickers": []}  # no company, no superlative -> ask, don't guess
