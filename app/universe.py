"""Dynamic company registry — seeds (config.COMPANIES) merged with on-demand ingested companies.

V4.0: pure plumbing. The dynamic registry file is written by the V4.1 ingest pipeline; until
that lands, data/dynamic/registry.json never exists, so every function here is identical in
behavior to reading config.COMPANIES/config.ALIASES directly. This module is the seam call
sites should use so V4.1 (open-universe ingest) needs no further call-site changes.
"""

from __future__ import annotations

import json

from app import config


def _load_dynamic() -> dict[str, dict]:
    """{ticker: {name, cik, accession, filing_date, ingested_at, last_used_at, ...}}."""
    path = config.DYNAMIC_REGISTRY_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def active_companies() -> dict[str, str]:
    """Ticker -> company name, seeds unioned with dynamically ingested companies."""
    merged = dict(config.COMPANIES)
    for ticker, entry in _load_dynamic().items():
        merged[ticker] = entry.get("name", ticker)
    return merged


def active_tickers() -> list[str]:
    return list(active_companies())


def aliases() -> dict[str, str]:
    """Lowercased alias -> ticker, seeds unioned with auto-generated dynamic aliases."""
    merged = dict(config.ALIASES)
    for ticker, entry in _load_dynamic().items():
        merged[ticker.lower()] = ticker
        name = entry.get("name", "")
        if name:
            merged[name.lower()] = ticker
    return merged


def is_ingested(ticker: str) -> bool:
    """True if `ticker` has a filing corpus loaded (seed or dynamic)."""
    ticker = ticker.upper()
    return ticker in config.COMPANIES or ticker in _load_dynamic()


def company_name(ticker: str) -> str:
    """Best-effort display name; falls back to the ticker itself if unknown."""
    return active_companies().get(ticker.upper(), ticker.upper())
