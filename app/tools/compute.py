"""Deterministic computations over tool evidence."""

from __future__ import annotations


def compute_metric(metric: str, inputs: dict | None = None, **_: object) -> dict:
    """Compute small ratios from explicit inputs.

    The agent only calls this when structured inputs are already available. It
    does not parse model prose or filing text.
    """
    inputs = inputs or {}
    if metric == "market_cap_to_revenue":
        market_cap = inputs.get("market_cap")
        revenue = inputs.get("revenue")
        if market_cap is None or revenue in (None, 0):
            return {"status": "missing_input", "data": {}, "evidence": []}
        ratio = market_cap / revenue
        return {"status": "ok", "data": {"metric": metric, "value": ratio}, "evidence": []}
    return {"status": "unsupported", "data": {"metric": metric}, "evidence": []}
