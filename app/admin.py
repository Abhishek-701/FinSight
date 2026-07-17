"""Admin aggregates over request_metrics + audit (V6.4) — computed in Python since sqlite has
no percentile_cont and demo traffic volume is small; not persisted, recomputed per call.
Gated to FINSIGHT_ADMIN_EMAILS (app.auth.is_admin) at the route layer, app/main.py.

Every ratio/percentile below is guarded for the empty-data case: a fresh deploy with zero
request_metrics rows must render a dashboard of zeros, not a 500 on first admin page load.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from app import audit, auth, config, metrics


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _model_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    # .get() with a zero-price default: a stored row can reference a model no longer in
    # MODEL_PRICES (renamed/retired) — cost estimation degrades to 0 for that slice rather
    # than raising mid-aggregation.
    in_price, out_price = config.MODEL_PRICES.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


def summary(days: int = 7) -> dict:
    since = (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0).isoformat()
    rows = metrics.window(since)

    total = len(rows)
    error_rows = [r for r in rows if r["status_code"] >= 500]
    error_rate = (len(error_rows) / total) if total else 0.0

    per_day: dict[str, dict] = defaultdict(lambda: {"count": 0, "errors": 0})
    latencies_by_route: dict[str, list[int]] = defaultdict(list)
    all_latencies: list[int] = []
    tokens_per_day: dict[str, dict] = defaultdict(lambda: {"input": 0, "output": 0})
    by_model: dict[str, dict] = defaultdict(lambda: {"input": 0, "output": 0, "calls": 0})
    input_total = output_total = embed_total = 0
    chat_rows = 0
    refused_rows = 0

    for r in rows:
        day = r["created_at"][:10]
        per_day[day]["count"] += 1
        if r["status_code"] >= 500:
            per_day[day]["errors"] += 1
        all_latencies.append(r["elapsed_ms"])
        latencies_by_route[r["route"]].append(r["elapsed_ms"])
        input_total += r["input_tokens"]
        output_total += r["output_tokens"]
        embed_total += r["embed_tokens"]
        tokens_per_day[day]["input"] += r["input_tokens"]
        tokens_per_day[day]["output"] += r["output_tokens"]
        for model, usage in r["models"].items():
            by_model[model]["input"] += usage.get("in", 0)
            by_model[model]["output"] += usage.get("out", 0)
            by_model[model]["calls"] += usage.get("calls", 0)
        if r["route"] == "/api/chat":
            chat_rows += 1
            if r["refused"]:
                refused_rows += 1

    by_model_list = [
        {
            "model": model, "input": u["input"], "output": u["output"], "calls": u["calls"],
            "est_cost_usd": round(_model_cost_usd(model, u["input"], u["output"]), 4),
        }
        for model, u in sorted(by_model.items())
    ]
    embed_cost = _model_cost_usd(config.EMBED_MODEL, embed_total, 0)
    est_cost_total = round(sum(m["est_cost_usd"] for m in by_model_list) + embed_cost, 4)

    by_route = sorted(
        (
            {
                "route": route, "count": len(lats),
                "p50": _percentile(lats, 0.5), "p95": _percentile(lats, 0.95),
            }
            for route, lats in latencies_by_route.items()
        ),
        key=lambda r: r["p95"] or 0, reverse=True,
    )

    audit_rows = audit.window(since)
    question_counts = Counter(
        (a["question"] or "").strip().lower() for a in audit_rows if a["question"]
    )
    top_questions = [
        {"question": q, "count": c} for q, c in question_counts.most_common(10)
    ]

    return {
        "window_days": days,
        "requests": {
            "total": total,
            "per_day": [
                {"date": d, "count": v["count"], "errors": v["errors"]}
                for d, v in sorted(per_day.items())
            ],
            "error_rate": round(error_rate, 4),
        },
        "latency_ms": {
            "overall": {"p50": _percentile(all_latencies, 0.5), "p95": _percentile(all_latencies, 0.95)},
            "by_route": by_route,
        },
        "tokens": {
            "input": input_total, "output": output_total, "embed": embed_total,
            "per_day": [
                {"date": d, "input": v["input"], "output": v["output"]}
                for d, v in sorted(tokens_per_day.items())
            ],
            "est_cost_usd": est_cost_total,
            "by_model": by_model_list,
        },
        "chat": {
            "turns": chat_rows,
            "refusal_rate": round(refused_rows / chat_rows, 4) if chat_rows else 0.0,
            "top_questions": top_questions,
        },
        "users": {
            "total": auth.count_users(),
            "active_sessions": auth.count_active_sessions(),
        },
    }
