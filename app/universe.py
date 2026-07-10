"""Dynamic company registry — seeds (config.COMPANIES) merged with on-demand ingested companies.

V4.0: pure plumbing. The dynamic registry file is written by the V4.1 ingest pipeline; until
that lands, data/dynamic/registry.json never exists, so every function here is identical in
behavior to reading config.COMPANIES/config.ALIASES directly. This module is the seam call
sites should use so V4.1 (open-universe ingest) needs no further call-site changes.
"""

from __future__ import annotations

import json
import re

from app import config

# EDGAR's `name` field is the full legal entity name (e.g. "Tesla, Inc.", "NVIDIA CORP"),
# which casual references never use ("Tesla", "NVIDIA"). Strip common corporate suffixes so
# the router's whole-word alias match still fires on how people actually talk.
_SUFFIX_RE = re.compile(
    r",?\s+(inc\.?|incorporated|corp\.?|corporation|co\.?|company|ltd\.?|limited|"
    r"plc|llc|l\.l\.c\.?|l\.p\.?|holdings?)\s*\.?$",
    re.I,
)


def _short_name(name: str) -> str:
    """Best-effort casual form of an EDGAR legal name, e.g. 'Tesla, Inc.' -> 'Tesla'."""
    short = _SUFFIX_RE.sub("", name).strip().rstrip(",")
    return short or name


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
    """Ticker -> casual display name, seeds unioned with dynamically ingested companies.

    Dynamic entries store EDGAR's full legal name ("Tesla, Inc."); displayed here in the
    same casual style as the seeds ("Apple", not "Apple Inc.") via _short_name().
    """
    merged = dict(config.COMPANIES)
    for ticker, entry in _load_dynamic().items():
        name = entry.get("name", ticker)
        merged[ticker] = _short_name(name) if name else ticker
    return merged


def active_tickers() -> list[str]:
    return list(active_companies())


def aliases() -> dict[str, str]:
    """Lowercased alias -> ticker, seeds unioned with auto-generated dynamic aliases.

    Each dynamic company contributes its ticker, its full EDGAR legal name, and a
    suffix-stripped casual form (e.g. "Tesla, Inc." -> also "tesla") — people ask about
    "Tesla", not "Tesla, Inc.".
    """
    merged = dict(config.ALIASES)
    for ticker, entry in _load_dynamic().items():
        merged[ticker.lower()] = ticker
        name = entry.get("name", "")
        if name:
            merged[name.lower()] = ticker
            merged[_short_name(name).lower()] = ticker
    return merged


def is_ingested(ticker: str) -> bool:
    """True if `ticker` has a filing corpus loaded (seed or dynamic)."""
    ticker = ticker.upper()
    return ticker in config.COMPANIES or ticker in _load_dynamic()


def company_name(ticker: str) -> str:
    """Best-effort display name; falls back to the ticker itself if unknown."""
    return active_companies().get(ticker.upper(), ticker.upper())
