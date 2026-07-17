"""FastAPI entrypoint for the financial research MVP.

Run the four checkpoint questions:  python -m app.main
(FastAPI/SSE endpoint is added to this file in Phase 4.)
"""

import json
import logging
import secrets
import time
import uuid
from collections import defaultdict, deque

import httpx
from fastapi import Header, HTTPException, Request
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import audit, auth, config, corpus, ingest_jobs, insight, metrics, obs, portfolio, research, screener, storage, universe, watchlist
from app.agent import session
from app.agent.context import from_history
from app.tools import market, news as news_tool

xbrl_lookup = research.xbrl_lookup
prepare = research.prepare
answer = research.answer


obs.setup_logging(config.LOG_LEVEL)
app = FastAPI()
log = logging.getLogger("fairway.api")

INDEX_HTML = config._ROOT / "static" / "index.html"
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)

_WEB_ASSETS = config.WEB_DIST / "assets"
if _WEB_ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=_WEB_ASSETS), name="web-assets")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    stream: bool = False
    client_id: str | None = None


class WatchlistRequest(BaseModel):
    client_id: str
    ticker: str


class PortfolioRequest(BaseModel):
    client_id: str
    ticker: str
    shares: float
    cost_basis: float | None = None


class WhatifTrade(BaseModel):
    ticker: str
    delta_shares: float


class WhatifRequest(BaseModel):
    client_id: str
    trades: list[WhatifTrade]


class ClaimRequest(BaseModel):
    client_id: str


def _guard(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    ident = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = _RATE_BUCKETS[ident]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= config.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    bucket.append(now)


def _corpus_status() -> dict:
    return corpus.status()


def _database_status() -> dict:
    started = time.perf_counter()
    try:
        conn = storage.connect(config.SESSION_DB_PATH)
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
        return {
            "backend": storage.backend_name(),
            "ok": True,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 — health check must never 500 the endpoint
        return {"backend": storage.backend_name(), "ok": False, "error": str(exc)}


def _startup_errors() -> list[str]:
    errors = []
    if not config.CHUNKS_PATH.exists():
        errors.append(f"Missing {config.CHUNKS_PATH}")
    if not config.FACTS_PATH.exists():
        errors.append(f"Missing {config.FACTS_PATH}")
    if not (config._ROOT / "data" / "chroma").exists():
        errors.append("Missing data/chroma")
    return errors


@app.on_event("startup")
def validate_startup() -> None:
    errors = _startup_errors()
    if errors:
        raise RuntimeError("; ".join(errors))


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    obs.seed(request_id)
    started = time.perf_counter()
    method, path = request.method, request.url.path

    def _route() -> str:
        route_obj = request.scope.get("route")
        return route_obj.path if route_obj else path

    def _finalize(status_code: int, stream_error: str | None) -> None:
        # Called immediately for ordinary responses, or after the body has fully drained for
        # StreamingResponse (SSE) — measuring elapsed_ms/tokens right after call_next returns
        # would undercount SSE responses, since call_next returns once headers are ready, well
        # before the generator has produced any body chunks.
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        snap = obs.snapshot()
        log.info(json.dumps({
            "request_id": request_id,
            "method": method,
            "path": path,
            "status_code": status_code,
            "elapsed_ms": elapsed_ms,
        }))
        if path.startswith("/api"):
            metrics.record({
                "request_id": request_id,
                "method": method,
                "route": _route(),
                "status_code": status_code,
                "elapsed_ms": elapsed_ms,
                "client_id": snap["extra"].get("client_id"),
                "llm_calls": snap["llm_calls"],
                "input_tokens": snap["input_tokens"],
                "output_tokens": snap["output_tokens"],
                "embed_tokens": snap["embed_tokens"],
                "models": snap["models"],
                "refused": snap["extra"].get("refused"),
                "error": stream_error or snap["extra"].get("error"),
            })

    try:
        response = await call_next(request)
    except Exception as exc:
        # Starlette wires a handler registered for the base `Exception` class (below) into
        # ServerErrorMiddleware, which sits ABOVE this middleware in the stack — so call_next()
        # still raises here even though the client will receive that handler's response (this
        # only affects handlers on the base Exception class; HTTPException and other specific
        # types are handled lower down and return through call_next normally). We can't see the
        # real Response object in this branch, but Starlette always treats Exception-class
        # handlers as 500s; record what we can here and re-raise so ServerErrorMiddleware still
        # runs the handler and sends the response.
        _finalize(500, str(exc))
        raise

    response.headers["x-request-id"] = request_id

    if hasattr(response, "body_iterator"):
        original_iterator = response.body_iterator

        async def _wrapped():
            stream_error: str | None = None
            try:
                async for chunk in original_iterator:
                    yield chunk
            except Exception as exc:  # noqa: BLE001 — still finalize on a broken/aborted stream
                stream_error = str(exc)
                raise
            finally:
                _finalize(response.status_code, stream_error)

        response.body_iterator = _wrapped()
    else:
        _finalize(response.status_code, None)

    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "internal_error"})


@app.get("/")
def index():
    dist_index = config.WEB_DIST / "index.html"
    return FileResponse(dist_index if dist_index.exists() else INDEX_HTML)


@app.get("/api/stream")
def stream(q: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return StreamingResponse(research.stream_events(q), media_type="text/event-stream")


@app.get("/api/research")
def research_result(q: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return research.run(q)


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, req.client_id)
    sid = req.session_id or session.new_session_id()
    if req.session_id:
        owner_id = session.owner(sid)
        if owner_id is not None and owner_id != client_id:
            # Someone else's session_id — a different anonymous client_id or a different
            # logged-in user. Same "not found" as an unknown id, so this doesn't confirm the
            # session exists to a caller who isn't its owner.
            raise HTTPException(status_code=404, detail="session_not_found")
    prior_history = session.history(sid)
    conversation_context = from_history(prior_history)
    session.append(sid, "user", req.message, client_id=client_id)
    obs.set_extra("client_id", client_id)
    if req.stream:
        def on_done(payload: dict) -> None:
            # The streaming path never used to persist the assistant turn or audit it — only
            # the non-streaming branch below did. Wired here via research.stream_events's
            # on_done hook, which fires once the full answer text is known.
            session.append(sid, "assistant", payload["answer_text"],
                            {"tool_calls": payload.get("tool_calls", [])}, client_id=client_id)
            obs.set_extra("refused", payload.get("refused", False))
            audit.record({
                "request_id": obs.get_request_id(),
                "session_id": sid,
                "client_id": client_id,
                "question": req.message,
                "contextualized_question": payload.get("contextualized_question"),
                "citations": payload.get("citations", []),
                "tool_calls": payload.get("tool_calls", []),
                "refused": payload.get("refused", False),
                "elapsed_ms": payload.get("elapsed_ms"),
            })

        def events():
            yield research.sse("session", {"session_id": sid})
            yield from research.stream_events(
                req.message, conversation_context, client_id, on_done=on_done,
            )
        return StreamingResponse(events(), media_type="text/event-stream")

    result = research.run(req.message, conversation_context, client_id)
    result["session_id"] = sid
    session.append(sid, "assistant", result["answer"], {"tool_calls": result.get("tool_calls", [])},
                    client_id=client_id)
    obs.set_extra("refused", result.get("refused", False))
    audit.record({
        "request_id": obs.get_request_id(),
        "session_id": sid,
        "client_id": client_id,
        "question": req.message,
        "contextualized_question": result.get("contextualized_question"),
        "citations": result.get("citations", []),
        "tool_calls": result.get("tool_calls", []),
        "refused": result.get("refused", False),
        "elapsed_ms": result.get("elapsed_ms"),
    })
    return result


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, request: Request, client_id: str | None = None,
                x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    resolved = auth.resolve_client_id(request, client_id)
    owner_id = session.owner(session_id)
    if owner_id is not None and owner_id != resolved:
        raise HTTPException(status_code=404, detail="session_not_found")
    return {"session_id": session_id, "messages": session.history(session_id)}


# --- Google OAuth (V6.3) — no _guard(): these are either top-level browser navigations that
# can't carry a custom x-api-key header (login/callback), or SPA fetch() calls that already
# don't send one today (me/logout/claim — same as every other frontend call), matching the
# existing no-guard precedent for GET /api/companies. Login is entirely optional/additive; if
# GOOGLE_CLIENT_ID/SECRET aren't set, login/callback 404 and the app works anonymously.
@app.get("/api/auth/google/login")
def auth_login():
    if not auth.is_configured():
        raise HTTPException(status_code=404, detail="oauth_not_configured")
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(auth.login_url(state))
    resp.set_cookie(auth.STATE_COOKIE, state, max_age=300, httponly=True,
                     secure=config.COOKIE_SECURE, samesite="lax")
    return resp


@app.get("/api/auth/google/callback")
def auth_callback(request: Request, code: str | None = None, state: str | None = None):
    expected_state = request.cookies.get(auth.STATE_COOKIE)
    if not auth.is_configured() or not code or not state or state != expected_state:
        resp = RedirectResponse("/?auth_error=1")
        resp.delete_cookie(auth.STATE_COOKIE)
        return resp
    try:
        token_response = auth.exchange_code(code)
        userinfo = auth.fetch_userinfo(token_response["access_token"])
        user = auth.upsert_user(userinfo)
    except Exception:  # noqa: BLE001 — any OAuth-flow failure lands on the same error redirect
        resp = RedirectResponse("/?auth_error=1")
        resp.delete_cookie(auth.STATE_COOKIE)
        return resp
    session_token = auth.create_session(user["id"])
    resp = RedirectResponse("/")
    resp.delete_cookie(auth.STATE_COOKIE)
    resp.set_cookie(auth.SESSION_COOKIE, session_token, max_age=60 * 60 * 24 * 30,
                     httponly=True, secure=config.COOKIE_SECURE, samesite="lax")
    return resp


def _user_payload(user: dict) -> dict:
    return {
        "id": user["id"], "email": user["email"], "name": user["name"],
        "picture": user["picture"], "claimed": user["claimed_client_id"] is not None,
    }


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = auth.current_user(request)
    if user is None:
        return {"user": None, "is_admin": False}
    return {"user": _user_payload(user), "is_admin": auth.is_admin(user)}


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.revoke_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


@app.post("/api/auth/claim")
def auth_claim(req: ClaimRequest, request: Request):
    user = auth.require_user(request)
    updated = auth.claim(user, req.client_id)
    return {"user": _user_payload(updated)}


@app.get("/api/quote/{ticker}")
def quote(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return market.market_quote(ticker)


@app.get("/api/news/{ticker}")
def news(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    result = news_tool.news_headlines(ticker)
    return {"status": result["status"], "data": result.get("data", {})}


@app.get("/api/companies")
def companies():
    return {"companies": universe.active_companies()}


@app.get("/api/watchlist")
def get_watchlist(client_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, client_id)
    return {"client_id": client_id, "items": watchlist.items(client_id)}


@app.post("/api/watchlist")
def add_watchlist(req: WatchlistRequest, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, req.client_id)
    try:
        items = watchlist.add(client_id, req.ticker)
    except ValueError:
        raise HTTPException(status_code=400, detail="unsupported_ticker")
    return {"ok": True, "items": items}


@app.delete("/api/watchlist/{ticker}")
def remove_watchlist(ticker: str, client_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, client_id)
    return {"ok": True, "items": watchlist.remove(client_id, ticker)}


@app.get("/api/quotes")
def quotes(tickers: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    symbols = [t.strip().upper() for t in tickers.split(",") if t.strip()][:10]
    return {"quotes": [market.market_quote(t) for t in symbols]}


@app.get("/api/history")
def history(tickers: str, request: Request, x_api_key: str | None = Header(default=None),
            period: str = "1mo"):
    _guard(request, x_api_key)
    if period not in config.MARKET_HISTORY_PERIODS:
        raise HTTPException(status_code=400, detail="unsupported_period")
    symbols = [t.strip().upper() for t in tickers.split(",") if t.strip()][:6]
    return {"histories": [market.market_history(t, period) for t in symbols]}


@app.get("/api/screener")
def screener_snapshot(request: Request, x_api_key: str | None = Header(default=None), live: int = 1):
    _guard(request, x_api_key)
    return screener.snapshot(include_market=bool(live))


@app.get("/api/portfolio")
def get_portfolio(client_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, client_id)
    return {"client_id": client_id, "items": portfolio.items(client_id)}


@app.post("/api/portfolio")
def set_portfolio_holding(req: PortfolioRequest, request: Request,
                          x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, req.client_id)
    try:
        items = portfolio.set_holding(client_id, req.ticker, req.shares, req.cost_basis)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"client_id": client_id, "items": items}


@app.delete("/api/portfolio/{ticker}")
def remove_portfolio_holding(ticker: str, client_id: str, request: Request,
                             x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, client_id)
    items = portfolio.remove(client_id, ticker)
    return {"client_id": client_id, "items": items}


@app.get("/api/portfolio/analysis")
def portfolio_analysis(client_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    """Live valuation, P&L (where a cost basis was entered), and concentration — the computed
    view; GET /api/portfolio above stays the plain editable holdings list."""
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, client_id)
    return portfolio.analyze(client_id)


@app.post("/api/portfolio/whatif")
def portfolio_whatif(req: WhatifRequest, request: Request, x_api_key: str | None = Header(default=None)):
    """Simulate hypothetical share deltas on top of current holdings — never persisted."""
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, req.client_id)
    trades = [{"ticker": t.ticker, "delta_shares": t.delta_shares} for t in req.trades]
    try:
        return portfolio.whatif(client_id, trades)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/portfolio/benchmark")
def portfolio_benchmark(
    client_id: str, request: Request, period: str = "3mo",
    x_api_key: str | None = Header(default=None),
):
    """Portfolio value history (today's shares, static weights) vs SPY over the same period."""
    _guard(request, x_api_key)
    client_id = auth.resolve_client_id(request, client_id)
    if period not in config.MARKET_HISTORY_PERIODS:
        raise HTTPException(status_code=400, detail="invalid_period")
    return portfolio.benchmark(client_id, period)


@app.get("/api/insight/{ticker}")
def insight_brief(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    ticker = ticker.upper()
    if not universe.is_ingested(ticker):
        raise HTTPException(status_code=400, detail="unsupported_ticker")
    return insight.brief(ticker)


@app.get("/api/insight/{ticker}/stream")
def insight_brief_stream(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    ticker = ticker.upper()
    if not universe.is_ingested(ticker):
        raise HTTPException(status_code=400, detail="unsupported_ticker")
    return StreamingResponse(insight.stream_brief(ticker), media_type="text/event-stream")


@app.post("/api/companies/{ticker}/ingest")
def start_company_ingest(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    """Kick off (or dedupe into) an on-demand ingest job for a not-yet-covered ticker.

    Async: returns immediately with a job snapshot; poll .../ingest/status or subscribe to
    .../ingest/stream for progress. 200 if the ticker is already ingested (no job started).
    """
    _guard(request, x_api_key)
    ticker = ticker.upper()
    if universe.is_ingested(ticker):
        return {"status": "already_ingested", "job": None}
    job = ingest_jobs.start_ingest(ticker)
    return {"status": job["status"], "job": job}


@app.get("/api/companies/{ticker}/ingest/status")
def company_ingest_status(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    ticker = ticker.upper()
    job = ingest_jobs.get_job(ticker)
    if job is None:
        if universe.is_ingested(ticker):
            return {"status": "already_ingested", "job": None}
        raise HTTPException(status_code=404, detail="no_ingest_job")
    return {"status": job["status"], "job": job}


@app.get("/api/companies/{ticker}/ingest/stream")
def company_ingest_stream(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    """SSE progress stream for an in-flight (or just-started) ingest job. Same wire format
    (`research.sse`) as /api/insight/{ticker}/stream, so the frontend reuses one SSE parser."""
    _guard(request, x_api_key)
    ticker = ticker.upper()

    def events():
        if universe.is_ingested(ticker):
            yield research.sse("done", {"status": "already_ingested"})
            return
        job = ingest_jobs.get_job(ticker) or ingest_jobs.start_ingest(ticker)
        last_sent = None
        while True:
            job = ingest_jobs.get_job(ticker)
            snapshot = (job["status"], job.get("stage"), job.get("pct"))
            if snapshot != last_sent:
                yield research.sse("progress", {
                    "status": job["status"], "stage": job.get("stage"), "pct": job.get("pct"),
                })
                last_sent = snapshot
            if job["status"] == "done":
                yield research.sse("done", {"status": "done", "result": job.get("result")})
                return
            if job["status"] == "error":
                yield research.sse("done", {"status": "error", "error": job.get("error")})
                return
            time.sleep(0.3)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/universe/resolve")
def universe_resolve(q: str, request: Request, x_api_key: str | None = Header(default=None)):
    """Resolve an EXACT ticker symbol or $cashtag against the full EDGAR universe (not just
    what we've ingested) — mirrors the chat-path resolver (app.universe.resolve_ticker) so a
    frontend can check "is this a real ticker?" with the same rules chat uses. For free-text
    company-name search ("rivian" -> RIVN), use /api/universe/search instead.
    """
    _guard(request, x_api_key)
    resolved = universe.resolve_ticker(q)
    if resolved is None:
        raise HTTPException(status_code=404, detail="not_found")
    ticker = resolved["ticker"]
    return {
        "ticker": ticker,
        "name": universe.company_name(ticker) if resolved["ingested"] else ticker,
        "cik": resolved["cik"],
        "ingested": resolved["ingested"],
    }


@app.get("/api/universe/search")
def universe_search(q: str, request: Request, x_api_key: str | None = Header(default=None)):
    """Free-text search over ticker symbols AND EDGAR company titles — the sidebar search
    box's name-discovery path. Ranked results, capped at 8; empty list (not 404) for no match
    or a too-short query, since this is typeahead, not a single-answer lookup."""
    _guard(request, x_api_key)
    if len(q.strip()) < 1:
        return {"results": []}
    return {"results": universe.search_companies(q, limit=8)}


@app.get("/api/corpus/status")
def corpus_status():
    return _corpus_status()


@app.get("/health")
def health():
    errors = _startup_errors()
    return {
        "ok": not errors,
        "errors": errors,
        "market_provider": config.MARKET_PROVIDER,
        "openai_configured": bool(config.OPENAI_API_KEY) if hasattr(config, "OPENAI_API_KEY") else None,
        "anthropic_configured": bool(config.ANTHROPIC_API_KEY) if hasattr(config, "ANTHROPIC_API_KEY") else None,
        "session_store": session.status(),
        "watchlist_store": watchlist.status(),
        "portfolio_store": portfolio.status(),
        "audit_log": audit.status(),
        "metrics_store": metrics.status(),
        "database": _database_status(),
        "corpus": _corpus_status(),
        "external_state": {
            "postgres_configured": bool(config.DATABASE_URL),
            "redis_configured": bool(config.REDIS_URL),
        },
    }


def _print(question: str, res: dict) -> None:
    print("\n" + "=" * 78)
    print("Q:", question)
    print("route:", res["route"])
    for r in res.get("retrieval", []):
        print(f"  sub[{r['ticker']}] top_sim={r['top_sim']}  q={r['query'][:60]!r}")
    if res.get("refused"):
        print(f"REFUSED ({res['refusal_reason']}): {res['answer']}")
        return
    print("\nANSWER:\n" + res["answer"])
    print("\ncitations:", res["citations"])
    print("gaps:", res["gaps"])


if __name__ == "__main__":
    questions = [
        "What was NVIDIA's total revenue?",
        "Which of these companies reported the highest R&D spend?",
        "What was Tesla's revenue?",
        "What is Coca-Cola's employee attrition rate?",
    ]
    for q in questions:
        _print(q, answer(q))
