"""Deterministic computations over tool evidence."""

from __future__ import annotations

from datetime import UTC, datetime


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _xbrl_fact_from_evidence(evidence: list[dict], concept_keywords: tuple[str, ...],
                             label: str = "annual_recent") -> tuple[str | None, str | None, float | None, str | None]:
    for chunk in evidence:
        if chunk.get("kind") != "xbrl":
            continue
        for fact in chunk.get("facts", []):
            concept = fact.get("concept", "").lower()
            if any(kw in concept for kw in concept_keywords) and fact.get("label") == label:
                return (
                    chunk.get("ticker"),
                    chunk.get("company"),
                    fact.get("value_scaled"),
                    chunk.get("chunk_id"),
                )
    return None, None, None, None


def _revenue_from_evidence(evidence: list[dict]) -> tuple[str | None, str | None, float | None, str | None]:
    return _xbrl_fact_from_evidence(evidence, ("revenue",))


def _price_from_evidence(evidence: list[dict]) -> tuple[float | None, str | None]:
    for chunk in evidence:
        if chunk.get("kind") == "market":
            price = chunk.get("data", {}).get("price")
            if price is not None:
                return price, chunk.get("chunk_id")
    return None, None


def _market_cap_from_evidence(evidence: list[dict]) -> tuple[float | None, str | None]:
    for chunk in evidence:
        if chunk.get("kind") == "market":
            market_cap = chunk.get("data", {}).get("market_cap")
            if market_cap is not None:
                return market_cap, chunk.get("chunk_id")
    return None, None


def _history_from_evidence(evidence: list[dict]) -> tuple[str | None, str | None, list[dict], str | None]:
    for chunk in evidence:
        if chunk.get("kind") == "market":
            rows = chunk.get("data", {}).get("rows")
            if rows:
                return chunk.get("ticker"), chunk.get("company"), rows, chunk.get("chunk_id")
    return None, None, [], None


def _compute_chunk(ticker: str, company: str, metric: str, value: float,
                   formula: str, inputs: dict, source_ids: list[str]) -> dict:
    as_of = _now_iso()
    chunk_id = f"{ticker}-CALC-{metric}-{as_of.replace('+00:00', 'Z').replace('-', '').replace(':', '')}"
    text = (
        f"[{company}] Deterministic calculation as of {as_of}. "
        f"Metric: {metric}. Formula: {formula}. Inputs: {inputs}. "
        f"Result: {value:.4f}. Source chunks: {', '.join(source_ids)}."
    )
    return {
        "chunk_id": chunk_id,
        "ticker": ticker,
        "company": company,
        "item": "Calculation",
        "section_title": "Deterministic Metric",
        "filing_date": as_of,
        "fused_score": 1.0,
        "text": text,
        "kind": "compute",
        "data": {"metric": metric, "value": value, "formula": formula, "inputs": inputs,
                 "source_ids": source_ids},
    }


def _compute_market_cap_to_revenue(metric: str, inputs: dict, evidence: list[dict]) -> dict:
    ticker, company, evidence_revenue, revenue_source = _revenue_from_evidence(evidence)
    evidence_market_cap, market_source = _market_cap_from_evidence(evidence)
    market_cap = inputs.get("market_cap", evidence_market_cap)
    revenue = inputs.get("revenue", evidence_revenue)
    if market_cap is None or revenue in (None, 0):
        return {"status": "missing_input", "data": {}, "evidence": []}
    ratio = market_cap / revenue
    source_ids = [sid for sid in [market_source, revenue_source] if sid]
    chunk = _compute_chunk(
        ticker or "CALC",
        company or "Computed Metric",
        metric,
        ratio,
        "market_cap / annual_revenue",
        {"market_cap": market_cap, "annual_revenue": revenue},
        source_ids,
    )
    return {"status": "ok", "data": chunk["data"], "evidence": [chunk]}


def _compute_pe_ratio(metric: str, inputs: dict, evidence: list[dict]) -> dict:
    price, price_source = _price_from_evidence(evidence)
    price = inputs.get("price", price)
    if price is not None:
        ticker, company, eps, eps_source = _xbrl_fact_from_evidence(evidence, ("earningspersharediluted",))
        formula = "price / eps_diluted"
        if eps is None:
            ticker, company, eps, eps_source = _xbrl_fact_from_evidence(evidence, ("earningspersharebasic",))
            formula = "price / eps_basic"
        eps = inputs.get("eps", eps)
        if eps not in (None, 0):
            ratio = price / eps
            source_ids = [sid for sid in [price_source, eps_source] if sid]
            chunk = _compute_chunk(
                ticker or "CALC", company or "Computed Metric", metric, ratio,
                formula, {"price": price, "eps": eps}, source_ids,
            )
            return {"status": "ok", "data": chunk["data"], "evidence": [chunk]}

    ticker, company, net_income, ni_source = _xbrl_fact_from_evidence(evidence, ("netincome", "profitloss"))
    net_income = inputs.get("net_income", net_income)
    market_cap, market_source = _market_cap_from_evidence(evidence)
    market_cap = inputs.get("market_cap", market_cap)
    if market_cap is None or net_income in (None, 0):
        return {"status": "missing_input", "data": {}, "evidence": []}
    ratio = market_cap / net_income
    source_ids = [sid for sid in [market_source, ni_source] if sid]
    chunk = _compute_chunk(
        ticker or "CALC", company or "Computed Metric", metric, ratio,
        "market_cap / net_income", {"market_cap": market_cap, "net_income": net_income}, source_ids,
    )
    return {"status": "ok", "data": chunk["data"], "evidence": [chunk]}


def _compute_price_change(metric: str, inputs: dict, evidence: list[dict]) -> dict:
    ticker, company, rows, source_id = _history_from_evidence(evidence)
    if len(rows) < 2:
        return {"status": "missing_input", "data": {}, "evidence": []}
    first, last = rows[0], rows[-1]
    first_close, last_close = first.get("close"), last.get("close")
    if first_close in (None, 0) or last_close is None:
        return {"status": "missing_input", "data": {}, "evidence": []}
    change_pct = (last_close - first_close) / first_close * 100
    chunk = _compute_chunk(
        ticker or "CALC", company or "Computed Metric", metric, change_pct,
        "(last_close - first_close) / first_close * 100",
        {"first_date": first.get("date"), "first_close": first_close,
         "last_date": last.get("date"), "last_close": last_close},
        [source_id] if source_id else [],
    )
    return {"status": "ok", "data": chunk["data"], "evidence": [chunk]}


_METRIC_HANDLERS = {
    "market_cap_to_revenue": _compute_market_cap_to_revenue,
    "ps_ratio": _compute_market_cap_to_revenue,
    "pe_ratio": _compute_pe_ratio,
    "price_change": _compute_price_change,
}


def compute_metric(metric: str, inputs: dict | None = None, evidence: list[dict] | None = None,
                   **_: object) -> dict:
    """Compute small ratios from explicit inputs.

    The agent only calls this when structured inputs are already available. It
    does not parse model prose or filing text.
    """
    handler = _METRIC_HANDLERS.get(metric)
    if handler is None:
        return {"status": "unsupported", "data": {"metric": metric}, "evidence": []}
    return handler(metric, inputs or {}, evidence or [])
