"""Bounded allowlist executor for agent tool plans."""

from __future__ import annotations

import time
from typing import Any

from app import config
from app.tools.registry import run_tool


def execute(actions: list[dict[str, Any]], context: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Run a bounded action list and return (tool_calls, evidence)."""
    tool_calls: list[dict] = []
    evidence: list[dict] = []
    for action in actions[: config.AGENT_MAX_STEPS]:
        tool = action["tool"]
        if tool == "synthesize_report":
            continue
        started = time.perf_counter()
        args = {**action.get("args", {})}
        args.setdefault("question", context.get("question"))
        args.setdefault("route", context.get("route"))
        result = run_tool(tool, **args)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        call = {k: v for k, v in result.items() if k not in {"meta", "evidence"}}
        call["elapsed_ms"] = elapsed_ms
        tool_calls.append(call)
        evidence.extend(result.get("evidence", []))
        if result.get("meta") is not None:
            context["meta"] = result["meta"]
    return tool_calls, evidence
