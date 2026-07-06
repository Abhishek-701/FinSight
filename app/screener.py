"""Cross-company screener: raw + derived XBRL metrics, optionally enriched with live quotes."""

from __future__ import annotations

from datetime import UTC, datetime

from app import config, facts
from app.tools import market

_RAW_METRICS = ("revenue", "operating_income", "net_income", "equity")
_MARKET_DEPENDENT = ("price", "market_cap", "ps_ratio")
DERIVED_METRICS = ("operating_margin", "net_margin", "revenue_growth_yoy", "roe", "ps_ratio")
ALL_METRICS = _RAW_METRICS + DERIVED_METRICS + ("price", "market_cap")


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _short_concept(concept: str) -> str:
    return concept.split(":")[-1]


def _xbrl_source_id(ticker: str, fact: dict) -> str:
    return f"{ticker}-XBRL-{_short_concept(fact['concept'])}"


def _row_for_ticker(ticker: str, include_market: bool) -> dict:
    company = config.COMPANIES[ticker]
    raw: dict[str, float | None] = {}
    sources: dict[str, str] = {}
    fiscal_period_end = None

    for metric in _RAW_METRICS:
        fact = facts.query(metric, ticker)
        raw[metric] = fact["value_scaled"] if fact else None
        if fact:
            sources[metric] = _xbrl_source_id(ticker, fact)
            if fiscal_period_end is None:
                fiscal_period_end = fact.get("period_end")

    revenue = raw["revenue"]
    operating_income = raw["operating_income"]
    net_income = raw["net_income"]
    equity = raw["equity"]

    operating_margin = operating_income / revenue if operating_income is not None and revenue else None
    net_margin = net_income / revenue if net_income is not None and revenue else None
    roe = net_income / equity if net_income is not None and equity else None

    recent, prior = facts.query_yoy("revenue", ticker)
    revenue_growth_yoy = None
    if recent and prior and prior.get("value_scaled"):
        revenue_growth_yoy = (recent["value_scaled"] - prior["value_scaled"]) / prior["value_scaled"]
    if recent:
        sources["revenue_growth_yoy"] = _xbrl_source_id(ticker, recent)

    price = market_cap = ps_ratio = None
    market_status = "skipped"
    if include_market:
        quote = market.market_quote(ticker)
        if quote["status"] == "ok":
            price = quote["data"]["price"]
            market_cap = quote["data"]["market_cap"]
            market_status = "ok"
            if market_cap is not None and revenue:
                ps_ratio = market_cap / revenue
        else:
            market_status = "unavailable"

    return {
        "ticker": ticker,
        "company": company,
        "fiscal_period_end": fiscal_period_end,
        "revenue": revenue,
        "operating_income": operating_income,
        "net_income": net_income,
        "equity": equity,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "revenue_growth_yoy": revenue_growth_yoy,
        "roe": roe,
        "price": price,
        "market_cap": market_cap,
        "ps_ratio": ps_ratio,
        "market_status": market_status,
        "sources": sources,
    }


def snapshot(include_market: bool = True) -> dict:
    """Return {"as_of", "rows", "disclaimer"} — one row per config.COMPANIES ticker."""
    rows = [_row_for_ticker(ticker, include_market) for ticker in config.COMPANIES]
    return {
        "as_of": _now_iso(),
        "rows": rows,
        "disclaimer": config.MARKET_DISCLAIMER if include_market else None,
    }


def rank(metric: str, order: str = "desc", rows: list[dict] | None = None) -> list[dict]:
    """Sort rows by metric, missing values last regardless of order."""
    if metric not in ALL_METRICS:
        raise ValueError(f"unknown_metric:{metric}")
    if rows is None:
        rows = snapshot(include_market=metric in _MARKET_DEPENDENT)["rows"]
    present = [r for r in rows if r.get(metric) is not None]
    missing = [r for r in rows if r.get(metric) is None]
    present.sort(key=lambda r: r[metric], reverse=(order != "asc"))
    return present + missing
