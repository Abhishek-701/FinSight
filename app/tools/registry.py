"""Allowlisted tool registry for bounded agent execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., dict[str, Any]]


class ToolResult(dict):
    """Dictionary result with a consistent status envelope."""


def _load_specs() -> dict[str, ToolSpec]:
    from app.tools import compute, filings, market

    specs = [
        ToolSpec("refuse_or_clarify", "Return a clarification refusal.", filings.refuse_or_clarify),
        ToolSpec("facts_lookup", "Lookup structured XBRL filing facts.", filings.facts_lookup),
        ToolSpec("filing_rag", "Run grounded retrieval over filing chunks.", filings.filing_rag),
        ToolSpec("multi_company_compare", "Run filing retrieval across multiple companies.", filings.filing_rag),
        ToolSpec("market_quote", "Fetch latest quote data for a ticker.", market.market_quote),
        ToolSpec("market_history", "Fetch recent OHLCV history for a ticker.", market.market_history),
        ToolSpec("compute_metric", "Compute simple ratios from tool evidence.", compute.compute_metric),
    ]
    return {spec.name: spec for spec in specs}


TOOL_REGISTRY: dict[str, ToolSpec] = _load_specs()


def run_tool(name: str, **kwargs: Any) -> ToolResult:
    if name not in TOOL_REGISTRY:
        return ToolResult({"tool": name, "status": "error", "error": "tool_not_allowed"})
    try:
        result = TOOL_REGISTRY[name].handler(**kwargs)
    except Exception as exc:  # noqa: BLE001 - tool boundary must return structured errors
        return ToolResult({"tool": name, "status": "error", "error": str(exc)})
    return ToolResult({"tool": name, **result})
