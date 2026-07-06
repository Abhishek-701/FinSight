"""Chat-agent tool: rank the six covered companies by a derived financial metric."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app import config, screener


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def screen_companies(metric: str = "operating_margin", order: str = "desc", **_: Any) -> dict:
    if metric not in screener.DERIVED_METRICS:
        return {"status": "unsupported", "data": {"metric": metric}, "evidence": []}

    include_market = metric == "ps_ratio"
    snap = screener.snapshot(include_market=include_market)
    ranked = screener.rank(metric, order=order, rows=snap["rows"])

    as_of = _now_iso()
    stamp = as_of.replace("+00:00", "Z").replace("-", "").replace(":", "")
    chunk_id = f"SCRN-{metric}-{stamp}"

    lines = [f"Ranked by {metric} ({order}):"]
    source_ids: list[str] = []
    for row in ranked:
        value = row.get(metric)
        source_id = row.get("sources", {}).get(metric)
        if source_id:
            source_ids.append(source_id)
        if value is None:
            if metric == "operating_margin" and row["ticker"] == "JPM":
                note = "not comparable — JPMorgan reports net revenue after interest expense, no comparable operating income line"
            else:
                note = "not available in this filing"
            lines.append(f"{row['ticker']} ({row['company']}): n/a — {note}")
        else:
            source_note = f" [{source_id}]" if source_id else ""
            lines.append(
                f"{row['ticker']} ({row['company']}): {value:.4f} "
                f"(fiscal period end {row.get('fiscal_period_end')}){source_note}"
            )
    if include_market:
        lines.append(f"{config.MARKET_DISCLAIMER} As of {snap['as_of']}.")

    chunk = {
        "chunk_id": chunk_id,
        "ticker": "SCRN",
        "company": "Screener",
        "item": "Screener",
        "section_title": "Cross-Company Ranking",
        "filing_date": as_of,
        "fused_score": 1.0,
        "text": "\n".join(lines),
        "kind": "screen",
        "data": {
            "metric": metric,
            "order": order,
            "rows": [
                {"ticker": r["ticker"], "value": r.get(metric), "fiscal_period_end": r.get("fiscal_period_end")}
                for r in ranked
            ],
            "source_ids": source_ids,
        },
    }
    return {"status": "ok", "data": chunk["data"], "evidence": [chunk]}
