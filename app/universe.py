"""Dynamic company registry — seeds (config.COMPANIES) merged with on-demand ingested companies.

V4.0: pure plumbing. The dynamic registry file is written by the V4.1 ingest pipeline; until
that lands, data/dynamic/registry.json never exists, so every function here is identical in
behavior to reading config.COMPANIES/config.ALIASES directly. This module is the seam call
sites should use so V4.1 (open-universe ingest) needs no further call-site changes.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime

from app import config

_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
# A bare uppercase token, 1-5 letters — candidate ticker symbol. Matched against the ORIGINAL
# (not lowercased) question text so casual lowercase words ("cat", "it", "a") never misfire;
# real tickers are conventionally written in caps ("Is CAT expensive?").
_UPPER_TOKEN_RE = re.compile(r"\b([A-Z]{1,5})\b")

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


def _write_dynamic(registry: dict[str, dict]) -> None:
    path = config.DYNAMIC_REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def register_ticker(ticker: str, entry: dict) -> None:
    """Write/overwrite one ticker's registry entry. Called as the LAST step of an ingest
    (ingest.pipeline) so nothing can observe the ticker as ingested before its data is ready."""
    ticker = ticker.upper()
    registry = _load_dynamic()
    registry[ticker] = entry
    _write_dynamic(registry)


def touch_ticker(ticker: str) -> None:
    """Bump last_used_at for a dynamic company — the LRU signal for eviction. No-op for seeds
    (never evicted) or for a ticker not (yet) in the registry."""
    ticker = ticker.upper()
    if ticker in config.COMPANIES:
        return
    registry = _load_dynamic()
    if ticker not in registry:
        return
    registry[ticker]["last_used_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    _write_dynamic(registry)


def least_recently_used_dynamic_ticker() -> str | None:
    """The dynamic ticker with the oldest last_used_at (falls back to ingested_at), or None if
    there are no dynamic companies. Used by app.ingest_jobs to pick an eviction target."""
    registry = _load_dynamic()
    if not registry:
        return None
    return min(
        registry, key=lambda t: registry[t].get("last_used_at") or registry[t].get("ingested_at", "")
    )


def evict_ticker(ticker: str) -> None:
    """Remove a dynamic company's registry entry, chunk/fact files, and Chroma vectors, then
    invalidate the retrieve/facts caches. Never call this on a seed — it only touches the
    dynamic registry, so seeds are structurally safe from it regardless."""
    from app import facts as facts_mod, retrieve

    ticker = ticker.upper()
    registry = _load_dynamic()
    if ticker not in registry:
        return

    try:
        import chromadb

        client = chromadb.PersistentClient(path=config.CHROMA_DIR)
        coll = client.get_collection(config.COLLECTION)
        coll.delete(where={"ticker": ticker})
    except Exception:  # noqa: BLE001 - eviction must not crash if Chroma is briefly unavailable
        pass

    (config.DYNAMIC_CHUNKS_DIR / f"{ticker}.json").unlink(missing_ok=True)
    (config.DYNAMIC_FACTS_DIR / f"{ticker}.json").unlink(missing_ok=True)

    registry.pop(ticker, None)
    _write_dynamic(registry)

    retrieve.invalidate()
    facts_mod.invalidate()


def _edgar_cache_is_fresh(path) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < config.CIK_MAP_TTL_HOURS * 3600


# (path_str, mtime, data) — process-lifetime cache so a hot path like resolve_ticker() (called
# from router.route() on any question naming an unrecognized entity) doesn't re-parse the ~1MB/
# 13k-entry EDGAR ticker map from disk on every single request; only on the first request after
# the on-disk file actually changes.
_cik_map_cache: tuple[str, float, dict] | None = None


def load_cik_map(force_refresh: bool = False) -> dict[str, str]:
    """Ticker -> CIK, disk- and memory-cached (EDGAR's own map is ~5MB and rarely changes).
    Shared by ingest.pipeline (actual ingest) and resolve_ticker() below (checking whether an
    unrecognized entity is a real, not-yet-ingested ticker) so both stay in sync off one file.
    """
    global _cik_map_cache
    from ingest import download  # local import: keeps this module's default import surface light

    path = config.DYNAMIC_CIK_MAP_PATH
    if not force_refresh and _edgar_cache_is_fresh(path):
        mtime = path.stat().st_mtime
        if _cik_map_cache and _cik_map_cache[:2] == (str(path), mtime):
            return _cik_map_cache[2]
        data = json.loads(path.read_text(encoding="utf-8"))
        _cik_map_cache = (str(path), mtime, data)
        return data
    cik_map = download.load_cik_map()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cik_map), encoding="utf-8")
    _cik_map_cache = (str(path), path.stat().st_mtime, cik_map)
    return cik_map


def lookup_cik(ticker: str) -> str | None:
    """CIK for `ticker`, or None if EDGAR has no such ticker. Refreshes the cache once on a
    miss (covers a ticker newly listed since our cache was last built)."""
    ticker = ticker.upper()
    cik_map = load_cik_map()
    if ticker not in cik_map:
        cik_map = load_cik_map(force_refresh=True)
    return cik_map.get(ticker)


# (path_str, mtime, data) — same process-lifetime caching pattern as _cik_map_cache above, for
# ticker -> EDGAR company title. Kept as an independent cache/fetch (not merged into
# load_cik_map) so the far more frequent chat-path lookup (lookup_cik, called on every
# unrecognized-entity question) never pays for title data it doesn't need.
_title_map_cache: tuple[str, float, dict] | None = None


def load_title_map(force_refresh: bool = False) -> dict[str, str]:
    """Ticker -> EDGAR company title (e.g. "Tesla, Inc."), disk- and memory-cached. Powers
    search_companies() below — the frontend search box's name-discovery path."""
    global _title_map_cache
    from ingest import download

    path = config.DYNAMIC_TITLE_MAP_PATH
    if not force_refresh and _edgar_cache_is_fresh(path):
        mtime = path.stat().st_mtime
        if _title_map_cache and _title_map_cache[:2] == (str(path), mtime):
            return _title_map_cache[2]
        data = json.loads(path.read_text(encoding="utf-8"))
        _title_map_cache = (str(path), mtime, data)
        return data
    title_map = download.load_ticker_titles()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(title_map), encoding="utf-8")
    _title_map_cache = (str(path), path.stat().st_mtime, title_map)
    return title_map


def search_companies(query: str, limit: int = 8) -> list[dict]:
    """Substring search over ticker symbols AND EDGAR company titles. This is the frontend
    search box's name-discovery path ("rivian" -> RIVN); chat's resolve_ticker() intentionally
    stays symbol/cashtag-only to avoid false positives in free-form prose.

    EDGAR's directory has ~13k tickers, many sharing a common word ("Apple Inc." vs "Apple
    iSports Group, Inc." vs "Pineapple Express Cannabis Co") — ranked so the well-known company
    a retail user means comes first: ticker-exact, then casual-name-exact (via _short_name,
    "Apple Inc." -> "Apple"), then title/ticker starts-with, then whole-word title match,
    then loose substring-anywhere as the last-resort fallback. Within a tier, shorter titles
    sort first (a proxy for "the canonical company", not a subsidiary/unrelated namesake).
    """
    q = query.strip().lower()
    if not q:
        return []
    try:
        titles = load_title_map()
    except Exception:  # noqa: BLE001 - EDGAR/network failure -> empty results, never a 500
        return []

    word_re = re.compile(rf"\b{re.escape(q)}\b")

    def rank(ticker: str, title: str) -> int:
        t, low_title = ticker.lower(), title.lower()
        if t == q:
            return 0
        if _short_name(title).lower() == q:
            return 1
        if low_title.startswith(q):
            return 2
        if t.startswith(q):
            return 3
        if word_re.search(low_title):
            return 4
        return 5  # loosest fallback: substring anywhere, e.g. "apple" inside "pineapple"

    hits = [
        (rank(ticker, title), len(title), ticker, title)
        for ticker, title in titles.items()
        if q in ticker.lower() or q in title.lower()
    ]
    hits.sort(key=lambda h: h[:3])
    return [
        {"ticker": ticker, "name": title, "ingested": is_ingested(ticker)}
        for _, _, ticker, title in hits[:limit]
    ]


# 1-3 consecutive Title-Case words, optional trailing possessive — a candidate company NAME
# ("Palantir", "Coca Cola"), as opposed to _UPPER_TOKEN_RE which candidates a ticker SYMBOL.
# Only ever checked for an EXACT casual-name match (see _short_name_index) — loose substring
# matching against free-form prose would false-positive constantly ("Is it a good time..." has
# plenty of capitalized sentence-starters that aren't company names).
_NAME_CANDIDATE_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})(?:'s)?\b")

# (id(title_map_dict), index) — cheap invalidation: load_title_map() returns the SAME cached
# dict object until it actually reloads from disk/network, so a change in id() means the
# underlying data changed and this index must be rebuilt.
_short_name_index_cache: tuple[int, dict[str, str]] | None = None


def _short_name_index() -> dict[str, str]:
    """Casual company name (lowercase) -> ticker, built once from load_title_map() and cached
    until the title map itself reloads.

    _short_name() only strips legal suffixes ("Inc.", "Corp."), not descriptive words — "Palantir
    Technologies Inc." reduces to "Palantir Technologies", not "Palantir". So this indexes both
    the full short name AND (for multi-word names) its first word alone, so "Palantir" still
    resolves. Exact short-name matches are added first and win any collision; first-word entries
    only fill gaps a full short name didn't already claim, e.g. a generic first word shared by
    several companies won't clobber a company whose ENTIRE short name is that word.
    """
    global _short_name_index_cache
    titles = load_title_map()
    if _short_name_index_cache is not None and _short_name_index_cache[0] == id(titles):
        return _short_name_index_cache[1]
    index: dict[str, str] = {}
    for ticker, title in titles.items():
        index.setdefault(_short_name(title).lower(), ticker)
    for ticker, title in titles.items():
        words = _short_name(title).split()
        if len(words) > 1:
            index.setdefault(words[0].lower(), ticker)
    _short_name_index_cache = (id(titles), index)
    return index


def _sub_phrases(phrase: str) -> list[str]:
    """All contiguous word sub-phrases of `phrase`, longest first: "Is Rivian" -> ["Is Rivian",
    "Is", "Rivian"]. _NAME_CANDIDATE_RE greedily grabs adjacent capitalized words together
    (a sentence-initial "Is"/"What" right before the actual company name), so the company name
    alone must still be tried once the full phrase doesn't match anything.
    """
    words = phrase.split()
    return [
        " ".join(words[start:start + length])
        for length in range(len(words), 0, -1)
        for start in range(len(words) - length + 1)
    ]


def resolve_ticker(text: str) -> dict | None:
    """Best-effort resolution of a candidate ticker/company mentioned in `text` against the
    FULL EDGAR ticker universe (not just active/ingested companies) — used by router.py to
    tell "a real company we haven't ingested yet" (offer to ingest) from "not a real entity"
    (out-of-corpus refusal).

    Returns {"ticker", "cik", "ingested"} for the first plausible match, or None. Checks
    aliases()/active_companies() first so an already-known company never triggers a network
    call. Candidates are tried in order: a $CASHTAG, a bare uppercase 1-5 letter token
    (case-sensitive — "cat"/"it"/"a" in lowercase prose never match), then an EXACT casual-name
    match ("Palantir" -> PLTR) so a retail user asking about a company by name — not just its
    ticker — still gets an ingest offer instead of a flat refusal.
    """
    known = aliases()
    low = text.lower()
    for alias, ticker in known.items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return {"ticker": ticker, "cik": None, "ingested": True}

    candidates = [m.group(1).upper() for m in _CASHTAG_RE.finditer(text)]
    candidates += [m.group(1) for m in _UPPER_TOKEN_RE.finditer(text)]
    if candidates:
        try:
            cik_map = load_cik_map()
        except Exception:  # noqa: BLE001 - EDGAR/network failure must not break routing; fall back to oos
            return None
        for candidate in candidates:
            cik = cik_map.get(candidate)
            if cik:
                return {"ticker": candidate, "cik": cik, "ingested": is_ingested(candidate)}

    name_candidates = [m.group(1) for m in _NAME_CANDIDATE_RE.finditer(text)]
    if not name_candidates:
        return None
    try:
        index = _short_name_index()
    except Exception:  # noqa: BLE001 - EDGAR/network failure must not break routing; fall back to oos
        return None
    for candidate in name_candidates:
        for phrase in _sub_phrases(candidate):
            ticker = index.get(phrase.lower())
            if ticker:
                cik = None
                try:
                    cik = load_cik_map().get(ticker)
                except Exception:  # noqa: BLE001 - cik is a display nicety here, not load-bearing
                    pass
                return {"ticker": ticker, "cik": cik, "ingested": is_ingested(ticker)}
    return None
