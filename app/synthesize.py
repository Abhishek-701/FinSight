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
    "You answer questions about six companies strictly from the provided evidence.\n"
    "The six companies are: Apple, JPMorgan Chase, Walmart, Coca-Cola, NVIDIA, and Caterpillar.\n"
    "Rules:\n"
    "- Use ONLY the provided context. Never use outside knowledge or guess a number.\n"
    "- Cite every figure inline with its chunk id in square brackets, e.g. [NVDA-0062] or [NVDA-MKT-...].\n"
    "- Treat SEC filings as historical/as-reported and market data as live or delayed as-of the quoted timestamp.\n"
    "- When using market data, state the as-of time and say it may be delayed and is not investment advice.\n"
    "- If the question is about a company other than the six listed above, say: "
    "'<Company> is not among the six companies I cover (Apple, JPMorgan Chase, Walmart, "
    "Coca-Cola, NVIDIA, Caterpillar). I cannot answer questions about it.' "
    "Do not describe which companies' data appeared in the context.\n"
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
        label = "as of" if c.get("kind") == "market" else "filed"
        hdr = f"[{c['chunk_id']}] {c['company']} — {c.get('section_title') or c.get('item') or ''} ({label} {c['filing_date']})"
        blocks.append(hdr + "\n" + c["text"])
    return "\n\n".join(blocks)


def build_xbrl_context(facts: list[dict]) -> tuple[str, list[dict]]:
    """Format XBRL fact dicts as synthetic chunks readable by stream_answer().

    Returns (context_string, synthetic_chunk_list). The chunk list has the same
    schema as RAG chunks so citation/gap logic in main.py works unchanged.

    Chunk IDs use the scheme  {TICKER}-XBRL-{concept_short}  so they are
    visually distinguishable from RAG chunk IDs (e.g. AAPL-XBRL-OperatingIncomeLoss).
    """
    from app import config  # local import avoids circular at module level

    company_facts: dict[str, list[dict]] = {}
    for f in facts:
        company_facts.setdefault(f["ticker"], []).append(f)

    synthetic_chunks: list[dict] = []
    for ticker, ticker_facts in company_facts.items():
        company = config.COMPANIES.get(ticker, ticker)
        # Use the period_end of the first fact as the filing period label.
        period_end = ticker_facts[0].get("period_end", "")
        filing_date = ticker_facts[0].get("filing_date", "")

        # Build a short concept name for the chunk ID (last CamelCase segment).
        def _short(concept: str) -> str:
            return concept.split(":")[-1]

        # One synthetic chunk per ticker, grouping all its facts.
        concept_short = "_".join(_short(f["concept"]) for f in ticker_facts[:2])
        chunk_id = f"{ticker}-XBRL-{concept_short}"

        # Text mimics the serialized-table format from parse.py so the model
        # treats it like any other financial statement excerpt.
        lines = [
            f"[{company}] Item 8: Financial Statements — XBRL-tagged consolidated figures "
            f"(period ending {period_end}, filed {filing_date}, in millions unless noted)"
        ]
        for f in ticker_facts:
            concept_label = _short(f["concept"])
            unit_note = " per share" if "pershare" in f["concept"].lower() else ""
            # Use each fact's own period_end (not the header's) so YoY rows show distinct dates.
            lines.append(
                f"Consolidated | {concept_label}{unit_note} | {f['period_end']} = {f['value_display']}"
            )

        chunk_text = "\n".join(lines)
        synthetic_chunks.append({
            "chunk_id": chunk_id,
            "ticker": ticker,
            "company": company,
            "item": "Item 8",
            "section_title": "Financial Statements (XBRL)",
            "filing_date": filing_date,
            "fused_score": 1.0,  # XBRL facts rank above RAG chunks
            "text": chunk_text,
            "kind": "xbrl",
        })

    context_str = build_context(synthetic_chunks)
    return context_str, synthetic_chunks


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
