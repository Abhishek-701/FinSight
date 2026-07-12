"""News provider abstraction — mirrors app/tools/market_provider.py.

Primary: yfinance's Ticker.news (already a dependency, no key, no quota). Its schema drifts
across releases (nested under "content" as of yfinance 1.4.x), so if it raises or returns
something we can't parse, get_provider() falls back to Yahoo Finance's public RSS feed —
same underlying source, more stable shape, no key either. Both return [] rather than raise
when a ticker genuinely has no headlines; the caller (app/tools/news.py) treats [] as a
citable "no recent headlines" envelope, not an error.
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse


class NewsProvider:
    name = "abstract"

    def headlines(self, ticker: str, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


class YFinanceNewsProvider(NewsProvider):
    name = "yfinance"

    def headlines(self, ticker: str, limit: int) -> list[dict[str, Any]]:
        import yfinance as yf

        raw = yf.Ticker(ticker).news or []
        items: list[dict[str, Any]] = []
        for entry in raw[:limit]:
            content = entry.get("content") or {}
            title = content.get("title")
            if not title:
                continue
            url = (
                (content.get("canonicalUrl") or {}).get("url")
                or (content.get("clickThroughUrl") or {}).get("url")
                or ""
            )
            items.append({
                "title": title,
                "publisher": (content.get("provider") or {}).get("displayName") or _domain(url),
                "published_at": content.get("pubDate") or content.get("displayTime") or "",
                "url": url,
                "summary": content.get("summary") or "",
            })
        return items


class YahooRssNewsProvider(NewsProvider):
    """Fallback when yfinance's .news schema breaks — same Yahoo Finance data, plain RSS."""

    name = "yahoo_rss"
    _URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}"

    def headlines(self, ticker: str, limit: int) -> list[dict[str, Any]]:
        req = urllib.request.Request(
            self._URL.format(ticker=ticker), headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)  # noqa: S314 - fixed, non-user-controlled Yahoo endpoint
        items: list[dict[str, Any]] = []
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            url = (item.findtext("link") or "").strip()
            items.append({
                "title": title,
                "publisher": _domain(url),
                "published_at": (item.findtext("pubDate") or "").strip(),
                "url": url,
                "summary": (item.findtext("description") or "").strip(),
            })
        return items


def get_provider() -> NewsProvider:
    return YFinanceNewsProvider()


def get_fallback_provider() -> NewsProvider:
    return YahooRssNewsProvider()
