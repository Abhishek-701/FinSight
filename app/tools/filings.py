"""Tool wrappers around the existing filings RAG and XBRL paths."""

from __future__ import annotations


def facts_lookup(question: str, route: dict, metrics: list[str] | None = None) -> dict:
    """Look up XBRL facts. When `metrics` is given explicitly (V3 valuation plans), those
    metrics are queried directly instead of re-detecting them from the question text — needed
    because questions like "is NVDA expensive?" don't match any XBRL keyword pattern.
    """
    from app import research

    meta = research.xbrl_lookup(question, route, metrics=metrics)
    return {
        "status": "hit" if meta else "miss",
        "metrics": metrics or research.detect_xbrl_metrics(question),
        "meta": meta,
        "evidence": meta.get("context_chunks", []) if meta else [],
    }


def refuse_or_clarify(question: str, route: dict) -> dict:
    from app import research

    meta = research.prepare(question, route)
    return {"status": "refused", "meta": meta, "evidence": []}


def filing_rag(question: str, route: dict) -> dict:
    from app import research

    meta = research.prepare(question, route)
    return {
        "status": "refused" if meta.get("refused") else "ok",
        "meta": meta,
        "evidence": meta.get("context_chunks", []),
        "retrieval": meta.get("retrieval", []),
    }
