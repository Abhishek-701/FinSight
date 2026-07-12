"""News headlines tool — mirrors app/tools/market.py's cache/chunk/status-envelope pattern.

One evidence chunk per ticker aggregating all headlines (not one per headline) so a
citation reads as "recent headlines" rather than flooding context with N separate sources —
mirrors how build_xbrl_context groups a company's facts into one chunk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app import config, universe
from app.tools.news_provider import get_fallback_provider, get_provider

try:
    from cachetools import TTLCache
except ImportError:  # pragma: no cover - keeps import-time behavior clear before deps install
    TTLCache = None

_NEWS_CACHE = TTLCache(maxsize=128, ttl=config.NEWS_CACHE_TTL_SECONDS) if TTLCache else {}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _fetch(ticker: str, limit: int) -> tuple[list[dict[str, Any]], str]:
    """(items, source_name). Falls back to the RSS provider on exception OR an empty primary
    result — an empty list from yfinance's often-brittle .news schema is as likely to mean
    "the API changed" as "no headlines", and the fallback is cheap."""
    try:
        primary = get_provider()
        items = primary.headlines(ticker, limit)
        if items:
            return items, primary.name
    except Exception:  # noqa: BLE001 - provider boundary always falls through to the backup
        pass
    try:
        fallback = get_fallback_provider()
        return fallback.headlines(ticker, limit), fallback.name
    except Exception:  # noqa: BLE001 - both providers down -> empty, not an error envelope
        return [], "unavailable"


def build_news_chunk(ticker: str, items: list[dict[str, Any]], source: str) -> dict:
    ticker = ticker.upper()
    company = universe.company_name(ticker)
    as_of = _now_iso()
    stamp = as_of.replace("+00:00", "Z").replace("-", "").replace(":", "")
    chunk_id = f"{ticker}-NEWS-{stamp}"
    if items:
        lines = [
            f"{i+1}. \"{it['title']}\" — {it.get('publisher') or 'unknown publisher'}, "
            f"{it.get('published_at') or 'date unknown'}"
            for i, it in enumerate(items)
        ]
        text = (
            f"[{company}] Recent headlines as of {as_of}, via {source} "
            f"(third-party reports; reported context, not a verified cause of any price move):\n"
            + "\n".join(lines)
        )
    else:
        text = (
            f"[{company}] No recent headlines were available from {source} as of {as_of}."
        )
    return {
        "chunk_id": chunk_id,
        "ticker": ticker,
        "company": company,
        "item": "News",
        "section_title": "Recent Headlines",
        "filing_date": as_of,
        "fused_score": 1.0,
        "text": text,
        "kind": "news",
        "source": source,
        "as_of": as_of,
        "data": {"items": items, "source": source, "as_of": as_of, "disclaimer": config.NEWS_DISCLAIMER},
    }


def news_headlines(ticker: str | None = None, limit: int | None = None, **_: Any) -> dict:
    ticker = (ticker or "").upper()
    if not ticker:
        return {"status": "missing_ticker", "data": {}, "evidence": []}
    limit = limit or config.NEWS_MAX_ITEMS

    if ticker in _NEWS_CACHE:
        items, source = _NEWS_CACHE[ticker]
        chunk = build_news_chunk(ticker, items, source)
        return {
            "status": "ok" if items else "empty", "cached": True,
            "data": chunk["data"], "evidence": [chunk],
        }

    items, source = _fetch(ticker, limit)
    _NEWS_CACHE[ticker] = (items, source)
    chunk = build_news_chunk(ticker, items, source)
    return {
        "status": "ok" if items else "empty", "cached": False,
        "data": chunk["data"], "evidence": [chunk],
    }
