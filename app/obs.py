"""Request-scoped observability: LLM/embedding token-usage accumulator + structured JSON
logging (V6.2).

The request_logging middleware (app/main.py) seeds a fresh accumulator dict per request via
a ContextVar; the four Anthropic call sites (app/decompose.py, app/agent/router_plan.py,
app/synthesize.py x2) and the OpenAI embeddings call site (app/retrieve.py) mutate it in
place. The middleware flushes it into a request_metrics row (app/metrics.py) once the
response body has fully drained — which also fixes the pre-existing bug where elapsed_ms was
measured right after `call_next` returns, before an SSE body has actually finished streaming.

In-place mutation only, never `request_ctx.set()` outside `seed()`: FastAPI/Starlette run
sync request handlers and generator response bodies through `run_in_threadpool` /
`iterate_in_threadpool`, which copy the current contextvars Context into a worker thread. A
fresh `.set()` there would be invisible to the request that started it, but mutating the dict
already held by that copied context *is* visible, since both point at the same dict object.

Every helper no-ops when no request is in flight (e.g. the V4.1 background ingest thread),
since those code paths never call `seed()`.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar

request_ctx: ContextVar[dict | None] = ContextVar("request_ctx", default=None)


def seed(request_id: str) -> None:
    request_ctx.set({
        "request_id": request_id,
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "embed_tokens": 0,
        "models": {},
        "extra": {},
    })


def get_request_id() -> str | None:
    ctx = request_ctx.get()
    return ctx["request_id"] if ctx else None


def add_llm_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    ctx = request_ctx.get()
    if ctx is None:
        return
    ctx["llm_calls"] += 1
    ctx["input_tokens"] += input_tokens
    ctx["output_tokens"] += output_tokens
    bucket = ctx["models"].setdefault(model, {"in": 0, "out": 0, "calls": 0})
    bucket["in"] += input_tokens
    bucket["out"] += output_tokens
    bucket["calls"] += 1


def add_embed_tokens(n: int) -> None:
    ctx = request_ctx.get()
    if ctx is None:
        return
    ctx["embed_tokens"] += n


def set_extra(key: str, value) -> None:
    ctx = request_ctx.get()
    if ctx is None:
        return
    ctx["extra"][key] = value


def snapshot() -> dict:
    """Copy of the current request's accumulator, or empty defaults if none is seeded (so
    callers outside a request — tests, scripts — get a harmless zero-valued dict back)."""
    ctx = request_ctx.get()
    if ctx is None:
        return {
            "request_id": None, "llm_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "embed_tokens": 0, "models": {}, "extra": {},
        }
    return {**ctx, "models": dict(ctx["models"]), "extra": dict(ctx["extra"])}


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_RequestIdFilter())
    root.handlers = [handler]
