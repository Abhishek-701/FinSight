"""Phase 3 — synthesis: stream a grounded answer from retrieved chunks, temp 0.

This is the SECOND refusal gate (the in-corpus-but-undisclosed case): the prompt forbids using
anything outside the provided context, so when a company's chunks were retrieved but lack the
asked figure, the model says "not found for <company>" instead of guessing. Citations are inline
[chunk_id]; gaps are derived afterward (a target company with no cited chunk).
"""

import anthropic

from app import config

_client = anthropic.Anthropic()

SYSTEM = (
    "You answer questions about six companies strictly from the provided 10-K excerpts.\n"
    "Rules:\n"
    "- Use ONLY the provided context. Never use outside knowledge or guess a number.\n"
    "- Cite every figure inline with its chunk id in square brackets, e.g. [NVDA-0062].\n"
    "- If the context does not contain the asked figure for a company, say plainly "
    "'Not found in the provided filings for <Company>.' Do not substitute a different metric.\n"
    "- In any cross-company comparison, state each company's fiscal year end next to its figure "
    "(fiscal years differ: Apple ends in September, NVIDIA and Walmart in January, others in December).\n"
    "- Prefer the CONSOLIDATED / total-company figure. If a number is a single segment or "
    "geographic breakdown (e.g. one reportable segment's revenue), label it as segment-level and "
    "do not present it as the company-wide total.\n"
    "- Be concise and factual. Report units as given (e.g. in millions)."
)


def build_context(chunks: list[dict]) -> str:
    blocks = []
    for c in chunks:
        hdr = f"[{c['chunk_id']}] {c['company']} — {c.get('section_title') or c.get('item') or ''} (filed {c['filing_date']})"
        blocks.append(hdr + "\n" + c["text"])
    return "\n\n".join(blocks)


def stream_answer(question: str, chunks: list[dict]):
    """Yield answer text chunks (for SSE). Caller accumulates for citations/gaps."""
    context = build_context(chunks)
    user = f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer using only the context above, citing chunk ids."
    with _client.messages.stream(
        model=config.CHAT_MODEL,
        max_tokens=1500,
        temperature=config.TEMPERATURE,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            yield text
