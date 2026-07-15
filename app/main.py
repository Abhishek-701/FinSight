"""FastAPI entrypoint for the financial research MVP.

Run the four checkpoint questions:  python -m app.main
(FastAPI/SSE endpoint is added to this file in Phase 4.)
"""

import json
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import audit, config, corpus, ingest_jobs, insight, portfolio, research, screener, universe, watchlist
from app.agent import session
from app.agent.context import from_history
from app.tools import market, news as news_tool

xbrl_lookup = research.xbrl_lookup
prepare = research.prepare
answer = research.answer


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
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    response.headers["x-request-id"] = request_id
    log.info(json.dumps({
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "elapsed_ms": elapsed_ms,
    }))
    return response


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
    sid = req.session_id or session.new_session_id()
    prior_history = session.history(sid)
    conversation_context = from_history(prior_history)
    session.append(sid, "user", req.message)
    if req.stream:
        def events():
            yield research.sse("session", {"session_id": sid})
            yield from research.stream_events(req.message, conversation_context, req.client_id)
        return StreamingResponse(events(), media_type="text/event-stream")

    result = research.run(req.message, conversation_context, req.client_id)
    result["session_id"] = sid
    session.append(sid, "assistant", result["answer"], {"tool_calls": result.get("tool_calls", [])})
    audit.record({
        "session_id": sid,
        "question": req.message,
        "contextualized_question": result.get("contextualized_question"),
        "citations": result.get("citations", []),
        "tool_calls": result.get("tool_calls", []),
        "refused": result.get("refused", False),
    })
    return result


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return {"session_id": session_id, "messages": session.history(session_id)}


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
    return {"client_id": client_id, "items": watchlist.items(client_id)}


@app.post("/api/watchlist")
def add_watchlist(req: WatchlistRequest, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    try:
        items = watchlist.add(req.client_id, req.ticker)
    except ValueError:
        raise HTTPException(status_code=400, detail="unsupported_ticker")
    return {"ok": True, "items": items}


@app.delete("/api/watchlist/{ticker}")
def remove_watchlist(ticker: str, client_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
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
    return {"client_id": client_id, "items": portfolio.items(client_id)}


@app.post("/api/portfolio")
def set_portfolio_holding(req: PortfolioRequest, request: Request,
                          x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    try:
        items = portfolio.set_holding(req.client_id, req.ticker, req.shares, req.cost_basis)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"client_id": req.client_id, "items": items}


@app.delete("/api/portfolio/{ticker}")
def remove_portfolio_holding(ticker: str, client_id: str, request: Request,
                             x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    items = portfolio.remove(client_id, ticker)
    return {"client_id": client_id, "items": items}


@app.get("/api/portfolio/analysis")
def portfolio_analysis(client_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    """Live valuation, P&L (where a cost basis was entered), and concentration — the computed
    view; GET /api/portfolio above stays the plain editable holdings list."""
    _guard(request, x_api_key)
    return portfolio.analyze(client_id)


@app.post("/api/portfolio/whatif")
def portfolio_whatif(req: WhatifRequest, request: Request, x_api_key: str | None = Header(default=None)):
    """Simulate hypothetical share deltas on top of current holdings — never persisted."""
    _guard(request, x_api_key)
    trades = [{"ticker": t.ticker, "delta_shares": t.delta_shares} for t in req.trades]
    try:
        return portfolio.whatif(req.client_id, trades)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/portfolio/benchmark")
def portfolio_benchmark(
    client_id: str, request: Request, period: str = "3mo",
    x_api_key: str | None = Header(default=None),
):
    """Portfolio value history (today's shares, static weights) vs SPY over the same period."""
    _guard(request, x_api_key)
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
