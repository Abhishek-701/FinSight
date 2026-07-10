"""On-demand per-ticker ingest pipeline (V4.1).

Reuses the exact same download/parse/chunk/xbrl logic as the six-seed-company batch
scripts (ingest/download.py, parse.py, chunk.py, xbrl.py) but:
  - writes to data/dynamic/{chunks,facts}/{TICKER}.json instead of the shared seed files
  - adds (never deletes/recreates) into the existing Chroma collection
  - never persists the downloaded raw HTML (seed ingest keeps data/raw/ for reproducibility;
    on-demand ingest re-fetches from EDGAR if a company needs to be re-ingested later)

ingest_ticker() raises IngestError (a typed, stable `.reason` code) for the failure modes
the caller should surface to a user rather than treat as a bug: unknown ticker, no 10-K on
file (20-F foreign filers, ETFs, SPACs), filing too large for the RAM budget.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from app import config, facts as facts_mod, retrieve
from ingest import chunk as chunk_mod
from ingest import download
from ingest import parse as parse_mod
from ingest import xbrl as xbrl_mod

ProgressCallback = Callable[[str, float], None]


class IngestError(Exception):
    """Typed ingest failure; `.reason` is a stable machine-readable code for the API/UI layer."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass
class IngestResult:
    ticker: str
    company: str
    cik: str
    accession: str
    filing_date: str
    chunk_count: int
    fact_count: int


def _noop_progress(stage: str, pct: float) -> None:
    pass


def _cik_map_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds < config.CIK_MAP_TTL_HOURS * 3600


def _load_cik_map(force_refresh: bool = False) -> dict[str, str]:
    """Ticker -> CIK, cached on disk (EDGAR's map rarely changes; avoid refetching it
    on every single-ticker ingest)."""
    path = config.DYNAMIC_CIK_MAP_PATH
    if not force_refresh and _cik_map_is_fresh(path):
        return json.loads(path.read_text(encoding="utf-8"))
    cik_map = download.load_cik_map()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cik_map), encoding="utf-8")
    return cik_map


def resolve_cik(ticker: str) -> str:
    """Look up a ticker's CIK, refreshing the cached map once if it's a cache miss
    (covers newly-listed tickers since our cache was built)."""
    ticker = ticker.upper()
    cik_map = _load_cik_map()
    if ticker not in cik_map:
        cik_map = _load_cik_map(force_refresh=True)
    if ticker not in cik_map:
        raise IngestError("ticker_not_found", f"{ticker} is not a registered SEC EDGAR ticker")
    return cik_map[ticker]


def _embed_and_add(chunks: list[dict]) -> None:
    """Add-only: embed and insert into the EXISTING Chroma collection (get_or_create, never
    delete_collection — that would wipe the seed companies' vectors)."""
    if not chunks:
        return
    import chromadb
    from openai import OpenAI

    from ingest.embed import embed_texts

    oai = OpenAI()
    embeddings = embed_texts(oai, [c["text"] for c in chunks])
    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    coll = client.get_or_create_collection(config.COLLECTION, metadata={"hnsw:space": "cosine"})
    metadatas = [{
        "ticker": c["ticker"], "company": c["company"],
        "item": c["item"] or "", "section_title": c["section_title"] or "",
        "accession": c["accession"], "filing_date": c["filing_date"], "kind": c["kind"],
    } for c in chunks]
    batch = 100
    for i in range(0, len(chunks), batch):
        coll.add(
            ids=[c["chunk_id"] for c in chunks[i:i + batch]],
            embeddings=embeddings[i:i + batch],
            documents=[c["text"] for c in chunks[i:i + batch]],
            metadatas=metadatas[i:i + batch],
        )


def _update_registry(ticker: str, company: str, cik: str, meta: dict, chunk_count: int) -> None:
    """Registry write is the LAST step (after chunks/facts are on disk and Chroma/BM25/facts
    caches are invalidated) so nothing can route to this ticker before its data is ready."""
    path = config.DYNAMIC_REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    registry: dict = {}
    if path.exists():
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            registry = {}
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    registry[ticker] = {
        "name": company,
        "cik": cik,
        "accession": meta["accession"],
        "filing_date": meta["filing_date"],
        "ingested_at": now,
        "last_used_at": now,
        "chunk_count": chunk_count,
    }
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def ingest_ticker(ticker: str, progress: ProgressCallback = _noop_progress) -> IngestResult:
    """Fetch, parse, chunk, embed, and fact-extract one company's latest 10-K on demand.

    Order matters: files land on disk, THEN Chroma is updated, THEN retrieve/facts caches
    are invalidated, THEN (last) the registry is written — so a concurrent question can
    never observe a ticker as "ingested" before its data is actually queryable.
    """
    ticker = ticker.upper()

    progress("resolving", 0.0)
    cik = resolve_cik(ticker)

    progress("downloading", 0.1)
    try:
        meta = download.latest_10k(cik)
    except RuntimeError as exc:
        raise IngestError("no_10k_available", str(exc)) from exc

    url = download.doc_url(cik, meta)
    html_bytes = download._get(url)  # noqa: SLF001 - internal reuse within the ingest package
    max_bytes = config.INGEST_MAX_RAW_MB * 1024 * 1024
    if len(html_bytes) > max_bytes:
        raise IngestError(
            "filing_too_large", f"{ticker}'s filing is over {config.INGEST_MAX_RAW_MB}MB"
        )
    html = html_bytes.decode("utf-8", errors="replace")
    company_name = meta.get("company_name") or ticker

    progress("parsing", 0.3)
    blocks = parse_mod.parse_filing(html, company_name, meta)

    progress("chunking", 0.5)
    chunks = chunk_mod.chunk_filing(ticker, blocks, meta)
    for c in chunks:
        c["company"] = company_name  # chunk_filing() falls back to its own NAMES dict otherwise

    progress("extracting_facts", 0.65)
    ticker_facts = xbrl_mod.extract_facts_from_html(html, ticker, meta["filing_date"])

    progress("embedding", 0.8)
    _embed_and_add(chunks)

    progress("saving", 0.95)
    config.DYNAMIC_CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    config.DYNAMIC_FACTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.DYNAMIC_CHUNKS_DIR / f"{ticker}.json").write_text(json.dumps(chunks), encoding="utf-8")
    (config.DYNAMIC_FACTS_DIR / f"{ticker}.json").write_text(json.dumps(ticker_facts), encoding="utf-8")

    retrieve.invalidate()
    facts_mod.invalidate()
    _update_registry(ticker, company_name, cik, meta, len(chunks))

    progress("done", 1.0)
    return IngestResult(
        ticker=ticker, company=company_name, cik=cik, accession=meta["accession"],
        filing_date=meta["filing_date"], chunk_count=len(chunks), fact_count=len(ticker_facts),
    )
