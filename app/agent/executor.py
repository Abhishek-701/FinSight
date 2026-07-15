"""Bounded allowlist executor for agent tool plans."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from app import config
from app.tools.registry import run_tool


def execute_events(
    actions: list[dict[str, Any]], context: dict[str, Any]
) -> Iterator[tuple[str, Any]]:
    """Run a bounded action list, yielding ("tool_start"|"tool_result", payload) as each step
    runs, then a final ("result", (tool_calls, evidence)) event. Lets callers (e.g. the SSE
    stream) surface live progress; execute() below just drains this and returns the result.
    """
    tool_calls: list[dict] = []
    evidence: list[dict] = []
    for action in actions[: config.AGENT_MAX_STEPS]:
        tool = action["tool"]
        if tool == "synthesize_report":
            continue
        yield "tool_start", {"tool": tool}
        started = time.perf_counter()
        args = {**action.get("args", {})}
        args.setdefault("question", context.get("question"))
        args.setdefault("route", context.get("route"))
        if tool == "compute_metric":
            args.setdefault("evidence", evidence)
        if tool == "portfolio_context":
            # Hard override, not setdefault: WHOSE portfolio this reads must come from the
            # authenticated request context, never from a plan (LLM-produced or otherwise) —
            # registry.py's arg_spec for this tool has no "client_id" key at all, so a plan
            # can't smuggle one in anyway, but this is the actual security boundary.
            args["client_id"] = context.get("client_id")
        result = run_tool(tool, **args)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        call = {k: v for k, v in result.items() if k not in {"meta", "evidence"}}
        call["elapsed_ms"] = elapsed_ms
        tool_calls.append(call)
        evidence.extend(result.get("evidence", []))
        if result.get("meta") is not None and context.get("meta") is None:
            context["meta"] = result["meta"]
        yield "tool_result", {"tool": tool, "status": call.get("status"), "elapsed_ms": elapsed_ms}
    yield "result", (tool_calls, evidence)


def execute(actions: list[dict[str, Any]], context: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Run a bounded action list and return (tool_calls, evidence)."""
    for kind, payload in execute_events(actions, context):
        if kind == "result":
            return payload
    return [], []  # pragma: no cover - execute_events always yields a final "result" event
