"""Phase 3 — hybrid retrieval: BM25 (lexical) + dense (embeddings) fused with reciprocal rank fusion.

The dense half also yields the NORMALIZED similarity of the top chunk, which the refusal gate
uses (RRF scores are rank-based and have no absolute meaning, so the gate must not sit on them).
"""

import json
import re
from functools import lru_cache

import chromadb
from openai import OpenAI
from rank_bm25 import BM25Okapi

from app import config

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tok(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _load_dynamic_chunks() -> list[dict]:
    """Chunks for on-demand ingested companies (V4.1 ingest pipeline writes these files).

    Empty today — data/dynamic/chunks/ doesn't exist until a company is ingested on demand.
    """
    directory = config.DYNAMIC_CHUNKS_DIR
    if not directory.exists():
        return []
    chunks: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            chunks.extend(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return chunks


@lru_cache(maxsize=1)
def _load():
    """Load chunks (seed + dynamic) + build the BM25 index and Chroma handle once (cached).

    Call invalidate() after ingesting/evicting a dynamic company so this rebuilds.
    """
    chunks = json.loads(open(config.CHUNKS_PATH, encoding="utf-8").read())
    chunks = chunks + _load_dynamic_chunks()
    by_id = {c["chunk_id"]: c for c in chunks}
    ids = [c["chunk_id"] for c in chunks]
    bm25 = BM25Okapi([_tok(c["text"]) for c in chunks])
    coll = chromadb.PersistentClient(path=config.CHROMA_DIR).get_collection(config.COLLECTION)
    return chunks, by_id, ids, bm25, coll


def invalidate() -> None:
    """Force the next retrieve() to reload chunks/BM25/Chroma handle from disk.

    Call after a dynamic company is ingested or evicted (app.ingest_jobs, V4.1).
    """
    _load.cache_clear()


@lru_cache(maxsize=256)
def _embed_query(query: str) -> tuple[float, ...]:
    resp = OpenAI().embeddings.create(model=config.EMBED_MODEL, input=[query])
    return tuple(resp.data[0].embedding)


def _dense(query: str, tickers: tuple[str, ...], n: int) -> list[tuple[str, float]]:
    """Return [(chunk_id, cosine_similarity)] best-first."""
    _, _, _, _, coll = _load()
    where = {"ticker": {"$in": list(tickers)}} if tickers else None
    res = coll.query(query_embeddings=[list(_embed_query(query))], n_results=n, where=where)
    ids, dists = res["ids"][0], res["distances"][0]
    return [(cid, 1.0 - dist) for cid, dist in zip(ids, dists)]  # cosine sim = 1 - cosine distance


def _bm25(query: str, tickers: tuple[str, ...], n: int) -> list[str]:
    chunks, _, ids, bm25, _ = _load()
    scores = bm25.get_scores(_tok(query))
    order = sorted(range(len(ids)), key=lambda i: scores[i], reverse=True)
    out = []
    for i in order:
        if tickers and chunks[i]["ticker"] not in tickers:
            continue
        out.append(ids[i])
        if len(out) >= n:
            break
    return out


def retrieve(query: str, tickers: list[str] | None, k: int) -> dict:
    """Hybrid retrieve. Returns {chunks: [chunk dict...], top_sim: float}.

    top_sim is the dense cosine similarity of the single best chunk (for the refusal gate)."""
    _, by_id, _, _, _ = _load()
    tkey = tuple(tickers or ())
    pool = config.RERANK_POOL if config.USE_RERANKER else max(k * 3, 20)
    dense = _dense(query, tkey, pool)
    sparse = _bm25(query, tkey, pool)
    top_sim = dense[0][1] if dense else 0.0  # gate uses dense sim, independent of reranking

    # Reciprocal rank fusion over the two ranked lists.
    fused: dict[str, float] = {}
    for rank, (cid, _) in enumerate(dense):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (config.RRF_K + rank)
    for rank, cid in enumerate(sparse):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (config.RRF_K + rank)

    fused_ids = sorted(fused, key=lambda c: fused[c], reverse=True)
    if config.USE_RERANKER:
        from app import rerank  # lazy import so the model only loads when enabled
        candidates = [{**by_id[cid], "fused_score": fused[cid]} for cid in fused_ids[:pool]]
        chunks = rerank.rerank(query, candidates)[:k]
    else:
        chunks = [{**by_id[cid], "fused_score": fused[cid]} for cid in fused_ids[:k]]
    return {"chunks": chunks, "top_sim": top_sim}
