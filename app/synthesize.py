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
    "\n"
    "Content rules:\n"
    "- Use ONLY the provided context. Never use outside knowledge or guess a number.\n"
    "- Cite every figure inline with its chunk id in square brackets, e.g. [NVDA-0062] or [NVDA-MKT-...].\n"
    "- Treat SEC filings as historical/as-reported; market data as live or delayed as-of the quoted timestamp.\n"
    "- When using market data, state the as-of time and note it may be delayed and is not investment advice.\n"
    "- If the question is about a company other than the six listed, say: "
    "'<Company> is not among the six companies I cover (Apple, JPMorgan Chase, Walmart, "
    "Coca-Cola, NVIDIA, Caterpillar). I cannot answer questions about it.' "
    "Do not describe which companies' data appeared in the context.\n"
    "- If the context does not contain the asked figure, say plainly "
    "'Not found in the provided filings for <Company>.' Do not substitute a different metric.\n"
    "- In cross-company comparisons, state each company's fiscal year end next to its figure "
    "(Apple ends September, NVIDIA and Walmart end January, others end December).\n"
    "- Prefer CONSOLIDATED figures. If a number is segment- or geography-level, label it as such.\n"
    "\n"
    "Formatting rules:\n"
    "- Write in markdown. Use **bold** for key figures, ## for major sections, ### for sub-sections,\n"
    "  - bullets for lists, and markdown tables for side-by-side comparisons of three or more values.\n"
    "- Lead with the answer, then the supporting evidence. Never open with 'Based on the provided\n"
    "  context' or 'Here is a summary' — go straight to the substance.\n"
    "- Only create a heading (## or ###) when you have at least two substantive sentences of evidence\n"
    "  to put under it. If context for a topic is thin, fold it into an adjacent paragraph instead.\n"
    "  Never write a heading followed immediately by a divider, another heading, or nothing.\n"
    "- For broad or open-ended questions, write flowing themed paragraphs. Do not produce a\n"
    "  report skeleton or outline — write only what the evidence supports, in full sentences.\n"
    "- Report numbers in the units given in the source (e.g. 'in millions'). Be concise and factual."
)


VALUATION_GUIDANCE = (
    "This question asks about valuation. Additional framing rules:\n"
    "- Valuation ratios (P/E, P/S) combine a live/delayed market price with historical filing "
    "figures — state that explicitly.\n"
    "- Give each ratio with its inputs, citing the [*-CALC-*] chunk that computed it; compare "
    "against peers using the [SCRN-*] chunk if present.\n"
    "- Never say a stock IS cheap/expensive or should be bought/sold. Describe where the ratio "
    "sits relative to the other covered companies and note this is not investment advice."
)
EXPLAIN_MOVE_GUIDANCE = (
    "This question asks why a stock price moved. Additional framing rules:\n"
    "- SEC filings do not explain short-term price moves. NEVER claim a filing-disclosed factor "
    "caused the move.\n"
    "- First state the move factually from market data with its as-of time, citing the "
    "[*-MKT-*] and [*-CALC-*] chunks.\n"
    "- Then present filing-disclosed factors investors may weigh (risks, segment exposure, "
    "outlook), each cited to a filing chunk, framed as context — use language like 'the filing "
    "discloses' or 'a risk factor investors may weigh is', never 'this caused the decline'.\n"
    "- If the filings contain nothing relevant to the move, say so plainly."
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
    from app import universe  # local import avoids circular at module level

    company_facts: dict[str, list[dict]] = {}
    for f in facts:
        company_facts.setdefault(f["ticker"], []).append(f)

    synthetic_chunks: list[dict] = []
    for ticker, ticker_facts in company_facts.items():
        company = universe.company_name(ticker)
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
            "facts": ticker_facts,
        })

    context_str = build_context(synthetic_chunks)
    return context_str, synthetic_chunks


def stream_answer(question: str, chunks: list[dict], guidance: str | None = None):
    """Yield answer text chunks (for SSE). Caller accumulates for citations/gaps."""
    context = build_context(chunks)
    user = f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer using only the context above, citing chunk ids."
    if guidance:
        user += f"\n\n{guidance}"
    with _client.messages.stream(
        model=config.CHAT_MODEL,
        max_tokens=2000,
        temperature=config.TEMPERATURE,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def stream_section(query: str, chunks: list[dict]):
    """Yield prose tokens for one sub-query topic.

    Called once per topic in the per-topic summary path. The model only sees
    one topic's chunks, so it writes focused prose instead of planning a
    multi-section skeleton it can't fill within the token budget.
    """
    context = build_context(chunks)
    user = (
        f"Context:\n{context}\n\n"
        f"Topic: {query}\n\n"
        "Write 3-5 sentences of focused prose for this specific topic only. "
        "No headings, no bullet points, no section markers. "
        "Cite every figure inline with its chunk id in square brackets."
    )
    with _client.messages.stream(
        model=config.CHAT_MODEL,
        max_tokens=600,
        temperature=config.TEMPERATURE,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def synthesize_section(query: str, chunks: list[dict]) -> str:
    """Synchronous wrapper around stream_section."""
    return "".join(stream_section(query, chunks))
