"""Phase 3 — decomposition: one temp-0 Claude call that rewrites a multi-company question into
one self-contained sub-query per company (structured JSON output). See locked architecture.
"""

import anthropic

from app import config, obs

_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env (loaded by config)

_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "enum": list(config.COMPANIES)},
                    "query": {"type": "string"},
                },
                "required": ["ticker", "query"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sub_queries"],
    "additionalProperties": False,
}


def decompose(question: str, tickers: list[str]) -> list[dict]:
    """Return [{ticker, query}] — one self-contained sub-query per target company."""
    targets = ", ".join(f"{t} ({config.COMPANIES[t]})" for t in tickers)
    system = (
        "You split a multi-company financial question into one self-contained sub-query per "
        "company, so each can be answered independently from that company's 10-K. Keep the same "
        "metric/intent; name the company explicitly in each sub-query. Output one sub_query per "
        "listed company, using its ticker."
    )
    msg = _client.messages.create(
        model=config.CHAT_MODEL,
        max_tokens=1024,
        temperature=config.TEMPERATURE,
        system=system,
        messages=[{"role": "user", "content": f"Companies: {targets}\nQuestion: {question}"}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    obs.add_llm_usage(config.CHAT_MODEL, msg.usage.input_tokens, msg.usage.output_tokens)
    import json
    text = next(b.text for b in msg.content if b.type == "text")
    subs = json.loads(text)["sub_queries"]
    # Keep only target companies; cap fan-out (G12 / locked architecture).
    seen, out = set(), []
    for s in subs:
        if s["ticker"] in tickers and s["ticker"] not in seen:
            seen.add(s["ticker"])
            out.append(s)
    return out[: config.FANOUT_CAP]
