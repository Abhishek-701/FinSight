"""yfinance-backed market data tools with a small TTL cache."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app import config
from app.tools.market_provider import get_provider

try:
    from cachetools import TTLCache
except ImportError:  # pragma: no cover - keeps import-time behavior clear before deps install
    TTLCache = None

_QUOTE_CACHE = TTLCache(maxsize=256, ttl=config.MARKET_CACHE_TTL_SECONDS) if TTLCache else {}
_HISTORY_CACHE = TTLCache(maxsize=128, ttl=config.MARKET_HISTORY_CACHE_TTL_SECONDS) if TTLCache else {}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _company(ticker: str) -> str:
    return config.COMPANIES.get(ticker.upper(), ticker.upper())


def _first(mapping: Any, *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def detect_market_intent(question: str) -> bool:
    import re

    return bool(re.search(config.MARKET_INTENT_RE, question, re.I))


def build_market_chunk(ticker: str, data: dict[str, Any], kind: str = "quote") -> dict:
    as_of = data.get("as_of") or _now_iso()
    stamp = as_of.replace("+00:00", "Z").replace("-", "").replace(":", "")
    chunk_id = f"{ticker.upper()}-MKT-{stamp}"
    company = _company(ticker)
    if kind == "history":
        # Full rows live in data (for REST callers/charts); the evidence TEXT the LLM sees
        # is capped to the tail so long periods (6mo/1y) don't bloat synthesis context.
        recent_rows = data.get("rows", [])[-config.MARKET_HISTORY_ROWS:]
        text = (
            f"[{company}] Market history from {data.get('source', config.MARKET_PROVIDER)} "
            f"as of {as_of}. Period: {data.get('period')}. "
            f"Most recent rows: {recent_rows}. This data may be delayed."
        )
    else:
        text = (
            f"[{company}] Market quote from {data.get('source', config.MARKET_PROVIDER)} "
            f"as of {as_of}. Price: {data.get('price')}. Previous close: {data.get('previous_close')}. "
            f"Change: {data.get('change')} ({data.get('change_percent')}%). "
            f"Market cap: {data.get('market_cap')}. This data may be delayed and is not investment advice."
        )
    return {
        "chunk_id": chunk_id,
        "ticker": ticker.upper(),
        "company": company,
        "item": "Market Data",
        "section_title": "Quote" if kind == "quote" else "Price History",
        "filing_date": as_of,
        "fused_score": 1.0,
        "text": text,
        "kind": "market",
        "source": data.get("source", config.MARKET_PROVIDER),
        "as_of": as_of,
        "data": data,
    }


def market_quote(ticker: str, **_: Any) -> dict:
    ticker = ticker.upper()
    if ticker in _QUOTE_CACHE:
        data = _QUOTE_CACHE[ticker]
        return {"status": "ok", "cached": True, "data": data, "evidence": [build_market_chunk(ticker, data)]}

    try:
        provider = get_provider()
        info = provider.quote(ticker)
    except ImportError:
        return {"status": "error", "error": "yfinance_not_installed", "evidence": []}
    except Exception as exc:  # noqa: BLE001 - provider boundary returns structured errors
        return {"status": "error", "error": f"market_provider_error:{exc}", "evidence": []}
    price = _first(info, "last_price", "regular_market_price", "lastPrice", "regularMarketPrice")
    previous_close = _first(info, "previous_close", "regularMarketPreviousClose", "previousClose")
    shares = _first(info, "shares", "sharesOutstanding")
    market_cap = _first(info, "market_cap", "marketCap")
    if market_cap is None and price is not None and shares is not None:
        market_cap = price * shares
    change = price - previous_close if price is not None and previous_close is not None else None
    change_percent = (change / previous_close * 100) if change is not None and previous_close else None
    data = {
        "ticker": ticker,
        "company": _company(ticker),
        "price": price,
        "previous_close": previous_close,
        "change": round(change, 4) if change is not None else None,
        "change_percent": round(change_percent, 2) if change_percent is not None else None,
        "market_cap": round(market_cap, 2) if market_cap is not None else None,
        "currency": _first(info, "currency"),
        "source": provider.name,
        "as_of": _now_iso(),
        "disclaimer": config.MARKET_DISCLAIMER,
    }
    _QUOTE_CACHE[ticker] = data
    return {"status": "ok", "cached": False, "data": data, "evidence": [build_market_chunk(ticker, data)]}


def market_history(ticker: str, period: str = "1mo", **_: Any) -> dict:
    ticker = ticker.upper()
    key = (ticker, period)
    if key in _HISTORY_CACHE:
        data = _HISTORY_CACHE[key]
        return {"status": "ok", "cached": True, "data": data, "evidence": [build_market_chunk(ticker, data, "history")]}

    try:
        provider = get_provider()
        hist = provider.history(ticker, period)
    except ImportError:
        return {"status": "error", "error": "yfinance_not_installed", "evidence": []}
    except Exception as exc:  # noqa: BLE001 - provider boundary returns structured errors
        return {"status": "error", "error": f"market_provider_error:{exc}", "evidence": []}
    rows = []
    if not hist.empty:
        for idx, row in hist.iterrows():
            rows.append({
                "date": str(idx.date()),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
    data = {
        "ticker": ticker,
        "company": _company(ticker),
        "period": period,
        "rows": rows,
        "source": provider.name,
        "as_of": _now_iso(),
        "disclaimer": config.MARKET_DISCLAIMER,
    }
    _HISTORY_CACHE[key] = data
    return {"status": "ok", "cached": False, "data": data, "evidence": [build_market_chunk(ticker, data, "history")]}
