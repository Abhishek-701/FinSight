"""Phase 5 — optional cross-encoder reranker.

Hybrid fusion ranks a buried table row (e.g. "Total revenues = 713,163" sitting among many
numeric rows) below prose that merely discusses revenue. A cross-encoder scores (query, chunk)
jointly, so it pulls the chunk that actually contains the answer to the top. Toggle via
config.USE_RERANKER so eval can measure the difference (see DECISIONS.md).
"""

from functools import lru_cache

from sentence_transformers import CrossEncoder

from app import config


@lru_cache(maxsize=1)
def _model() -> CrossEncoder:
    return CrossEncoder(config.RERANK_MODEL)


def rerank(query: str, chunks: list[dict]) -> list[dict]:
    """Reorder chunks best-first by cross-encoder relevance to the query."""
    if not chunks:
        return chunks
    scores = _model().predict([(query, c["text"]) for c in chunks])
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    return [chunks[i] for i in order]
